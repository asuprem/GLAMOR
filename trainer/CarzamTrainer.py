import torch
import tqdm, shutil, os
from collections import defaultdict
import sklearn.cluster, sklearn.metrics.cluster
import numpy as np
import utils.math
import loss.builders
from .BaseTrainer import BaseTrainer

class CarzamTrainer(BaseTrainer):
    try:
        # apex = __import__('apex')
        apex = None
    except:
        apex = None
    def __init__(   self, 
                    model: torch.nn.Module, 
                    loss_fn: loss.builders.LossBuilder, 
                    optimizer: torch.optim.Optimizer, loss_optimizer: torch.optim.Optimizer, 
                    scheduler: torch.optim.lr_scheduler._LRScheduler, loss_scheduler: torch.optim.lr_scheduler._LRScheduler, 
                    train_loader, test_loader, 
                    queries, epochs, logger, test_mode="zsl", **kwargs):
        
        super(CarzamTrainer,self).__init__(model, loss_fn, optimizer, loss_optimizer, scheduler, loss_scheduler, train_loader, test_loader, epochs, logger)

        self.queries = queries
        self.test_mode = test_mode
        self.loss = []

    # setup inherited from BaseTrainer
    
    def step(self,batch):
        self.model.train()
        self.optimizer.zero_grad()
        if self.loss_optimizer is not None: # In case loss functions have no differentiable parameters
            self.loss_optimizer.zero_grad()
        batch_kwargs = {}
        batch_kwargs["epoch"] = self.global_epoch
        img, batch_kwargs["labels"] = batch
        img, batch_kwargs["labels"] = img.cuda(), batch_kwargs["labels"].cuda()
        # logits, features, labels
        batch_kwargs["logits"], batch_kwargs["features"] = self.model(img)
        loss = self.loss_fn(**batch_kwargs)
        if self.fp16 and self.apex is not None:
            with self.apex.amp.scale_loss(loss, self.optimizer) as scaled_loss:
                scaled_loss.backward()
        else:
            loss.backward()
        self.optimizer.step()
        if self.loss_optimizer is not None: # In case loss functions have no differentiable parameters
            self.loss_optimizer.step()
        
        self.loss.append(loss.cpu().item())

    def train(self,continue_epoch = 0):    
        self.logger.info("Starting training")
        self.logger.info("Logging to:\t%s"%self.logger_file)
        self.logger.info("Models will be saved to local directory:\t%s"%self.save_directory)
        if self.save_backup:
            self.logger.info("Models will be backed up to drive directory:\t%s"%self.backup_directory)
        self.logger.info("Models will be saved with base name:\t%s_epoch[].pth"%self.model_save_name)
        self.logger.info("Optimizers will be saved with base name:\t%s_epoch[]_optimizer.pth"%self.model_save_name)
        self.logger.info("Schedulers will be saved with base name:\t%s_epoch[]_scheduler.pth"%self.model_save_name)
        

        if continue_epoch > 0:
            load_epoch = continue_epoch - 1
            self.load(load_epoch)

        self.logger.info("Performing initial evaluation...")
        self.evaluate(suffix="Pretest")

        for epoch in range(self.epochs):
            if epoch >= continue_epoch:
                for batch in self.train_loader:
                    if not self.global_batch:
                        lrs = self.scheduler.get_lr(); lrs = sum(lrs)/float(len(lrs))
                        self.logger.info("Starting epoch {0} with {1} steps and learning rate {2:2.5E}".format(epoch, len(self.train_loader) - (len(self.train_loader)%10), lrs))
                    self.step(batch)
                    self.global_batch += 1
                    if (self.global_batch + 1) % self.step_verbose == 0:
                        loss_avg = sum(self.loss[-100:]) / float(len(self.loss[-100:]))
                        self.logger.info('Epoch{0}.{1}\tTotal Loss: {2:.3f}'.format(self.global_epoch, self.global_batch, loss_avg))
                self.global_batch = 0
                self.scheduler.step()
                if self.loss_scheduler is not None:
                    self.loss_scheduler.step()
                self.logger.info('{0} Completed epoch {1} {2}'.format('*'*10, self.global_epoch, '*'*10))
                if self.global_epoch % self.test_frequency == 0:
                    self.evaluate()
                if self.global_epoch % self.save_frequency == 0:
                    self.save()
                self.global_epoch += 1
            else:
                self.global_epoch = epoch+1

    def save(self):
        self.logger.info("Saving model, optimizer, and scheduler.")
        MODEL_SAVE = self.model_save_name + '_epoch%i'%self.global_epoch + '.pth'
        OPTIM_SAVE = self.model_save_name + '_epoch%i'%self.global_epoch + '_optimizer.pth'
        SCHEDULER_SAVE = self.model_save_name + '_epoch%i'%self.global_epoch + '_scheduler.pth'
        LOSS_SAVE = self.model_save_name + "_epoch%i"%self.global_epoch + "_loss.pth"
        LOSS_OPTIMIZER_SAVE = self.model_save_name + "_epoch%i"%self.global_epoch + "_loss_optimizer.pth"
        LOSS_SCHEDULER_SAVE = self.model_save_name + "_epoch%i"%self.global_epoch + "_loss_scheduler.pth"

        torch.save(self.model.state_dict(), os.path.join(self.save_directory, MODEL_SAVE))
        torch.save(self.optimizer.state_dict(), os.path.join(self.save_directory, OPTIM_SAVE))
        torch.save(self.scheduler.state_dict(), os.path.join(self.save_directory, SCHEDULER_SAVE))
        torch.save(self.loss_fn.state_dict(), os.path.join(self.save_directory, LOSS_SAVE))

        if self.loss_optimizer is not None: # For loss funtions with empty parameters
            torch.save(self.loss_optimizer.state_dict(), os.path.join(self.save_directory, LOSS_OPTIMIZER_SAVE))
        if self.loss_scheduler is not None: # For loss funtions with empty parameters
            torch.save(self.loss_scheduler.state_dict(), os.path.join(self.save_directory, LOSS_SCHEDULER_SAVE))

        if self.save_backup:
            shutil.copy2(os.path.join(self.save_directory, MODEL_SAVE), self.backup_directory)
            shutil.copy2(os.path.join(self.save_directory, OPTIM_SAVE), self.backup_directory)
            shutil.copy2(os.path.join(self.save_directory, SCHEDULER_SAVE), self.backup_directory)
            shutil.copy2(os.path.join(self.save_directory, LOSS_SAVE), self.backup_directory)
            if self.loss_optimizer is not None: # For loss funtions with empty parameters
                shutil.copy2(os.path.join(self.save_directory, LOSS_OPTIMIZER_SAVE), self.backup_directory)
            if self.loss_scheduler is not None: # For loss funtions with empty parameters
                shutil.copy2(os.path.join(self.save_directory, LOSS_SCHEDULER_SAVE), self.backup_directory)
            self.logger.info("Performing drive backup of model, optimizer, and scheduler.")
            
            LOGGER_SAVE = os.path.join(self.backup_directory, self.logger_file)
            if os.path.exists(LOGGER_SAVE):
                os.remove(LOGGER_SAVE)
            shutil.copy2(os.path.join(self.save_directory, self.logger_file), LOGGER_SAVE)
    
    def load(self, load_epoch):
        self.logger.info("Resuming training from epoch %i. Loading saved state from %i"%(load_epoch+1,load_epoch))
        model_load = self.model_save_name + '_epoch%i'%load_epoch + '.pth'
        optim_load = self.model_save_name + '_epoch%i'%load_epoch + '_optimizer.pth'
        scheduler_load = self.model_save_name + '_epoch%i'%load_epoch + '_scheduler.pth'
        loss_load = self.model_save_name + "_epoch%i"%load_epoch + "_loss.pth"
        loss_optimizer_load = self.model_save_name + "_epoch%i"%load_epoch + "_loss_optimizer.pth"
        loss_scheduler_load = self.model_save_name + "_epoch%i"%load_epoch + "_loss_scheduler.pth"

        if self.save_backup:
            self.logger.info("Loading model, optimizer, and scheduler from drive backup.")
            model_load_path = os.path.join(self.backup_directory, model_load)
            optim_load_path = os.path.join(self.backup_directory, optim_load)
            scheduler_load_path = os.path.join(self.backup_directory, scheduler_load)
            loss_load_path = os.path.join(self.backup_directory, loss_load)
            loss_optimizer_load_path = os.path.join(self.backup_directory, loss_optimizer_load)
            loss_scheduler_load_path = os.path.join(self.backup_directory, loss_scheduler_load)
        else:
            self.logger.info("Loading model, optimizer, and scheduler from local backup.")
            model_load_path = os.path.join(self.save_directory, model_load)
            optim_load_path = os.path.join(self.save_directory, optim_load)
            scheduler_load_path = os.path.join(self.save_directory, scheduler_load)
            loss_load_path = os.path.join(self.save_directory, loss_load)
            loss_optimizer_load_path = os.path.join(self.save_directory, loss_optimizer_load)
            loss_scheduler_load_path = os.path.join(self.save_directory, loss_scheduler_load)

        self.model.load_state_dict(torch.load(model_load_path))
        self.logger.info("Finished loading model state_dict from %s"%model_load_path)
        self.optimizer.load_state_dict(torch.load(optim_load_path))
        self.logger.info("Finished loading optimizer state_dict from %s"%optim_load_path)
        self.scheduler.load_state_dict(torch.load(scheduler_load_path))
        self.logger.info("Finished loading scheduler state_dict from %s"%scheduler_load_path)
        self.loss_fn.load_state_dict(torch.load(loss_load_path))
        self.logger.info("Finished loading loss state_dict from %s"%loss_load_path)

        if self.loss_optimizer is not None: # For loss funtions with empty parameters
            self.loss_optimizer.load_state_dict(torch.load(loss_optimizer_load_path))
        if self.loss_scheduler is not None: # For loss funtions with empty parameters
            self.loss_scheduler.load_state_dict(torch.load(loss_scheduler_load_path))
        self.logger.info("Finished loading loss state_dict from %s"%loss_load_path)
    
    def evaluate(self, suffix=""):
        self.logger.info('Validation in progress')

        self.model.eval()
        features, pids, cids = [], [], []
        with torch.no_grad():
            # self.queries --> number of test classees
            for batch in tqdm.tqdm(self.test_loader, total=len(self.test_loader), leave=False):

                data, pid = batch
                data = data.cuda()
                
                feature = self.model(data).detach().cpu()
                features.append(feature)
                pids.append(pid)

        features, pids = torch.cat(features, dim=0), torch.cat(pids, dim=0)
        
        # K-means cluster into the number of known classes (i.e. queries = # of classes)
        self.logger.info('Performing k-means clustering of features into {} classes'.format(self.queries))
        clusters = self.kmeans_cluster(features, self.queries)
        self.logger.info('Calculating normalizaed mutual information between labels and assigned cluster')
        nmi = self.nmi(pids, clusters)

        # TODO magic number 8
        self.logger.info('Assigning labels using nearest neighbors')
        cluster_labels = self.kmeans_labels(features, pids, 8)
        self.logger.info('Computing CMC curve')
        cmc = self.cmc(cluster_labels, true_labels=pids, cmc_ranks=range(10))

        if self.test_mode == "gzsl":
            cmc_s = self.cmc(cluster_labels[pids<self.queries//2], true_labels=pids[pids<self.queries//2], cmc_ranks=range(8))
            cmc_u = self.cmc(cluster_labels[pids>=self.queries//2], true_labels=pids[pids>=self.queries//2], cmc_ranks=range(8))
            harmonic_cmc = (2*cmc_s[0]*cmc_u[0])/(cmc_s[0]+cmc_u[0])
        
        
        

        self.logger.info("Completed all calculations")
        self.logger.info('NMI{}: {:0.5%}'.format(suffix, nmi))
        if self.test_mode == "gzsl":
            self.logger.info('Harmonic-mean{}: {:0.5%}'.format(suffix, harmonic_cmc))
        
        
        for r in range(10):
            self.logger.info('CMC Rank-{}{}: {:.2%}'.format(r+1, suffix, cmc[r]))

        if self.test_mode == "gzsl":
            for r in range(8):
                self.logger.info('CMC-Seen Rank-{}{}: {:.2%}'.format(r+1, suffix, cmc_s[r]))
            for r in range(8):
                self.logger.info('CMC-Unseen Rank-{}{}: {:.2%}'.format(r+1, suffix, cmc_u[r]))


  
    def kmeans_cluster(self,features, classes):
        return sklearn.cluster.MiniBatchKMeans(n_clusters=classes).fit(features).labels_

    def nmi(self,labels, clusters):
        return sklearn.metrics.cluster.normalized_mutual_info_score(labels_true=labels, labels_pred=clusters)

    def kmeans_labels(self, features, labels, neighbors):
        dist = utils.math.pairwise_distance(features)
        nearest_indices = np.argsort(dist.numpy(), axis=1)[:,1:neighbors+1]
        return np.array([[labels[i] for i in nearest_idx] for nearest_idx in nearest_indices])

    def cmc(self, predicted_labels, true_labels, cmc_ranks):
        true_labels = true_labels.numpy()
        cmc_curve=[]
        for rank_ in cmc_ranks:
            cmc_rank = sum([1 for true_, pred_ in zip(true_labels, predicted_labels) if true_ in pred_[:rank_+1]])
            cmc_rank /= (1.*len(true_labels))
            cmc_curve.append(cmc_rank)
        return cmc_curve
            