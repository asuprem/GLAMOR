from torch import nn
import torch
import pdb

class ChannelAttention(nn.Module):
    def __init__(self, in_planes, ratio=16):
        super(ChannelAttention, self).__init__()
        self.avg_pool = nn.AdaptiveAvgPool2d(1)
        self.max_pool = nn.AdaptiveMaxPool2d(1)

        self.fc1   = nn.Conv2d(in_planes, in_planes // 16, 1, bias=False)
        self.relu1 = nn.ReLU()
        self.fc2   = nn.Conv2d(in_planes // 16, in_planes, 1, bias=False)

        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        avg_out = self.fc2(self.relu1(self.fc1(self.avg_pool(x))))
        max_out = self.fc2(self.relu1(self.fc1(self.max_pool(x))))
        out = avg_out + max_out
        return self.sigmoid(out)

class SpatialAttention(nn.Module):
    def __init__(self, kernel_size=7):
        super(SpatialAttention, self).__init__()

        assert kernel_size in (3, 7), 'kernel size must be 3 or 7'
        padding = 3 if kernel_size == 7 else 1

        self.conv1 = nn.Conv2d(2, 1, kernel_size, padding=padding, bias=False)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        avg_out = torch.mean(x, dim=1, keepdim=True)
        max_out, _ = torch.max(x, dim=1, keepdim=True)
        x = torch.cat([avg_out, max_out], dim=1)
        x = self.conv1(x)
        return self.sigmoid(x)

class DenseAttention(nn.Module):    # Like spatial, but for all channels
    def __init__(self, planes):
        super(DenseAttention, self).__init__()
        self.dense_conv1=nn.Conv2d(planes,planes,kernel_size=3,padding=1,bias=False)
        self.dense_relu1=nn.LeakyReLU()
        self.dense_conv2=nn.Conv2d(planes,planes,kernel_size=3,padding=1,bias=False)
        self.dense_sigmoid = nn.Sigmoid()
    def forward(self,x):
        x = self.dense_conv1(x)
        x = self.dense_relu1(x)
        x = self.dense_conv2(x)
        x = self.dense_sigmoid(x)
        return x

class InputAttention(nn.Module):
    def __init__(self, planes):
        super(InputAttention, self).__init__()
        self.ia_conv1=nn.Conv2d(planes,planes,kernel_size=3,padding=1,bias=False)
        self.ia_relu1=nn.LeakyReLU()
        self.ia_conv2=nn.Conv2d(planes,planes,kernel_size=3,padding=1,bias=False)
        self.ia_sigmoid = nn.Sigmoid()
    def forward(self,x):
        x = self.ia_conv1(x)
        x = self.ia_relu1(x)
        x = self.ia_conv2(x)
        x = self.ia_sigmoid(x)
        return x

class BasicBlock(nn.Module):
    expansion = 1

    def __init__(self, inplanes, planes, stride=1, downsample=None, groups=1,
                 base_width=64, dilation=1, norm_layer=None, 
                 attention=None, input_attention=False, part_attention=False):
        super(BasicBlock, self).__init__()
        if norm_layer is None:
            norm_layer = nn.BatchNorm2d
        if groups != 1 or base_width != 64:
            raise ValueError('BasicBlock only supports groups=1 and base_width=64')
        if dilation > 1:
            raise NotImplementedError("Dilation > 1 not supported in BasicBlock")
        # Both self.conv1 and self.downsample layers downsample the input when stride != 1
        self.conv1 = nn.Conv2d(inplanes, planes, kernel_size=3, stride=stride, padding=1, bias=False, groups=1, dilation=1)
        self.bn1 = norm_layer(planes)
        self.relu = nn.ReLU(inplace=True)
        self.conv2 = nn.Conv2d(planes, planes, kernel_size=3, stride=1, padding=1, bias=False, groups=1, dilation=1)
        self.bn2 = norm_layer(planes)       
        
        if input_attention:
            self.input_attention = InputAttention(planes)
        else:
            self.input_attention = None

        if attention is None:
            self.ca = None
            self.sa = None
        elif attention == 'cbam':
            self.ca = ChannelAttention(planes)
            self.sa = SpatialAttention(kernel_size=3)
        elif attention == 'dbam':
            self.ca = ChannelAttention(planes)
            self.sa = DenseAttention(planes)
        else:
            raise NotImplementedError()

        if part_attention:
            self.p_sa = DenseAttention(planes=planes*self.expansion)
            self.p_ca = ChannelAttention(planes*self.expansion)
        else:
            self.p_ca = None
            self.p_sa = None

        self.downsample = downsample
        self.stride = stride

    def forward(self, x):
        identity = x

        if self.input_attention is not None:
            x = self.input_attention(x) * x
        
        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.bn2(out)

        if self.ca is not None:
            out = self.ca(out) * out
            out = self.sa(out) * out

        if self.downsample is not None:
            identity = self.downsample(x)

        p_out = out
        part_mask = None
        if self.p_ca is not None:   # Get part attention
            p_out = self.p_sa(p_out) * p_out
#            p_out = self.p_ca(p_out) * p_out
            p_out = self.relu(p_out)
            part_mask = self.p_ca(p_out)

        out = out + identity
        out = self.relu(out)

        if self.p_ca is not None:   # Concat part attention
            #out = torch.cat([p_out[:,p_out.shape[1]//2:,:,:],out[:,:p_out.shape[1]//2,:,:]],dim=1)
            out = (part_mask * p_out) + ((1-part_mask)*out)
        return out

class Bottleneck(nn.Module):
    expansion = 4

    def __init__(   self, inplanes, planes, stride=1, downsample=None, groups = 1, base_width = 64, dilation = 1, norm_layer=None, 
                    attention = None, input_attention=False, part_attention=False):
        super(Bottleneck, self).__init__()
        if norm_layer is None:
            norm_layer = nn.BatchNorm2d
        width = int(planes * (base_width / 64.)) * groups
        
        self.conv1 = nn.Conv2d(inplanes, width, kernel_size=1, bias=False,stride=1)
        self.bn1 = norm_layer(width)
        self.conv2 = nn.Conv2d(width, width, kernel_size=3, stride=stride, padding=dilation, bias=False, groups=groups, dilation=dilation)
        self.bn2 = norm_layer(width)
        self.conv3 = nn.Conv2d(width, planes * self.expansion, kernel_size=1, bias=False, stride=1)
        self.bn3 = norm_layer(planes * self.expansion)
        self.relu = nn.ReLU(inplace=True)
        
        if input_attention:
            self.input_attention = InputAttention(planes)
        else:
            self.input_attention = None

        if attention is None:
            self.ca = None
            self.sa = None
        elif attention == 'cbam':
            self.sa = SpatialAttention(kernel_size=3)
            self.ca = ChannelAttention(planes*self.expansion)
        elif attention == 'dbam':
            self.ca = ChannelAttention(planes)
            self.sa = DenseAttention(planes)
        else:
            raise NotImplementedError()

        if part_attention:
            self.p_sa = DenseAttention(planes=planes*self.expansion)
            self.p_ca = ChannelAttention(planes*self.expansion)
        else:
            self.p_ca = None
            self.p_sa = None
        
        self.downsample = downsample
        self.stride = stride

    def forward(self, x):
        identity = x

        if self.input_attention is not None:
            x = self.input_attention(x) * x

        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.bn2(out)
        out = self.relu(out)

        out = self.conv3(out)
        out = self.bn3(out)

        if self.ca is not None:
            out = self.ca(out) * out
            out = self.sa(out) * out

        if self.downsample is not None:
            identity = self.downsample(x)

        p_out = out
        part_mask = None
        if self.p_ca is not None:   # Get part attention
            p_out = self.p_sa(p_out) * p_out
#            p_out = self.p_ca(p_out) * p_out
            p_out = self.relu(p_out)
            part_mask = self.p_ca(p_out)
        
        out = out + identity
        out = self.relu(out)

        if self.p_ca is not None:   # Concat part attention
            #out = torch.cat([p_out[:,p_out.shape[1]//2:,:,:],out[:,:p_out.shape[1]//2,:,:]],dim=1)
            out = (part_mask * p_out) + ((1-part_mask)*out)
        return out

class ResNet(nn.Module):
    def __init__(self, block=Bottleneck, layers=[3, 4, 6, 3], last_stride=2, zero_init_residual=False, \
                    top_only=True, num_classes=1000, groups=1, width_per_group=64, replace_stride_with_dilation=None,norm_layer=None, 
                    attention=None, input_attention = None, secondary_attention=None, ia_attention = None, part_attention = None,
                    **kwargs):
        super().__init__()
        self.attention=attention
        self.input_attention=input_attention
        self.secondary_attention=secondary_attention
        self.block=block
        self.inplanes = 64
        if norm_layer is None:
            self._norm_layer = nn.BatchNorm2d
        #elif norm_layer == "ln":
        #    self._norm_layer = nn.LayerNorm
        self.dilation = 1
        if replace_stride_with_dilation is None:
            replace_stride_with_dilation = [False, False, False]
        if len(replace_stride_with_dilation) != 3:
            raise ValueError("replace_stride_with_dilation should be `None` or a 3-element tuple. Got {}".format(replace_stride_with_dilation))
        self.groups = groups
        self.base_width = width_per_group

        self.conv1 = nn.Conv2d(3, self.inplanes, kernel_size=7, stride=2, padding=3, bias=False)
        #if norm_layer == "gn":
        #    self.bn1 = nn.GroupNorm2d
        self.bn1 = nn.BatchNorm2d(self.inplanes)
        self.relu1 = nn.ReLU(inplace=True)
        self.maxpool = nn.MaxPool2d(kernel_size=3, stride=2, padding=1)

        self.ia_attention = ia_attention
        self.part_attention = part_attention
        
        # Make sure ia and input_attention do not conflict
        if self.ia_attention is not None and self.input_attention is not None:
            raise ValueError("Cannot have both ia_attention and input_attention.")
        if self.part_attention is not None and (self.attention is not None and self.secondary_attention is None):
            raise ValueError("Cannot have part-attention with CBAM everywhere")
        if self.part_attention is not None and (self.attention is not None and self.secondary_attention==1):
            raise ValueError("Cannot have part-attention with CBAM-Early")

        # Create true IA
        if self.ia_attention:
            self.ia_attention = InputAttention(self.inplanes)   # 64, set above
        else:
            self.ia_attention = None

        att = self.attention
        if secondary_attention is not None and secondary_attention != 1: # leave alone if sec attention not set
            att = None
        self.layer1 = self._make_layer(self.block, 64, layers[0], attention = att, input_attention=self.input_attention, part_attention = self.part_attention)
        att = self.attention
        if secondary_attention is not None and secondary_attention != 2: # leave alone if sec attention not set
            att = None
        self.layer2 = self._make_layer(self.block, 128, layers[1], stride=2, attention = att, dilate=replace_stride_with_dilation[0])
        att = self.attention
        if secondary_attention is not None and secondary_attention != 3: # leave alone if sec attention not set
            att = None
        self.layer3 = self._make_layer(self.block, 256, layers[2], stride=2, attention = att, dilate=replace_stride_with_dilation[1])
        att = self.attention
        if secondary_attention is not None and secondary_attention != 4: # leave alone if sec attention not set
            att = None
        self.layer4 = self._make_layer(self.block, 512, layers[3], stride=last_stride, attention = att, dilate=replace_stride_with_dilation[2])
        
        self.top_only = top_only
        self.avgpool, self.fc = None, None

        if not self.top_only:
            self.avgpool = nn.AdaptiveAvgPool2d((1, 1))
            self.fc = nn.Linear(512 * block.expansion, num_classes)
    
    def _make_layer(self, block, planes, blocks, stride=1, dilate = False, attention = None, input_attention=False, ia_attention = False, part_attention = False):
        downsample = None
        previous_dilation = self.dilation
        if dilate:
            self.dilation *= stride
            stride = 1
        if stride != 1 or self.inplanes != planes * block.expansion:
            downsample = nn.Sequential(
                nn.Conv2d(self.inplanes, planes * block.expansion,
                            kernel_size=1, stride=stride, bias=False),
                self._norm_layer(planes * block.expansion),
            )
    
        layers = []
        layers.append(block(self.inplanes, planes, stride, downsample,groups = self.groups, base_width = self.base_width, dilation = previous_dilation, norm_layer=self._norm_layer, attention=attention, input_attention=input_attention, part_attention=part_attention))
        self.inplanes = planes * block.expansion
        for _ in range(1, blocks):
            layers.append(block(self.inplanes, planes, groups = self.groups, base_width = self.base_width, dilation = self.dilation, norm_layer=self._norm_layer, attention=attention))
        return nn.Sequential(*layers)
    
    def forward(self, x):
        x = self.conv1(x)
        
        if self.ia_attention is not None:
            x = self.ia_attention(x) * x
        x = self.bn1(x)
        x = self.relu1(x)
        x = self.maxpool(x)
    
        x = self.layer1(x)
        x = self.layer2(x)
        x = self.layer3(x)
        x = self.layer4(x)

        if not self.top_only:
            x = self.avgpool(x)
            x = torch.flatten(x,1)
            x = self.fc(x)            
        return x
    
    def load_param(self, weights_path):
        param_dict = torch.load(weights_path)
        for i in param_dict:
            if 'fc' in i and self.top_only:
                continue
            self.state_dict()[i].copy_(param_dict[i])
            
            
def _resnet(arch, block, layers, pretrained, progress, **kwargs):
    model = ResNet(block, layers, **kwargs)
    return model


def resnet18(pretrained=False, progress=True, **kwargs):
    r"""ResNet-18 model from
    `"Deep Residual Learning for Image Recognition" <https://arxiv.org/pdf/1512.03385.pdf>`_
    Args:
        pretrained (bool): If True, returns a model pre-trained on ImageNet
        progress (bool): If True, displays a progress bar of the download to stderr
    """
    return _resnet('resnet18', BasicBlock, [2, 2, 2, 2], pretrained, progress,
                   **kwargs)


def resnet34(pretrained=False, progress=True, **kwargs):
    r"""ResNet-34 model from
    `"Deep Residual Learning for Image Recognition" <https://arxiv.org/pdf/1512.03385.pdf>`_
    Args:
        pretrained (bool): If True, returns a model pre-trained on ImageNet
        progress (bool): If True, displays a progress bar of the download to stderr
    """
    return _resnet('resnet34', BasicBlock, [3, 4, 6, 3], pretrained, progress,
                   **kwargs)


def resnet50(pretrained=False, progress=True, **kwargs):
    r"""ResNet-50 model from
    `"Deep Residual Learning for Image Recognition" <https://arxiv.org/pdf/1512.03385.pdf>`_
    Args:
        pretrained (bool): If True, returns a model pre-trained on ImageNet
        progress (bool): If True, displays a progress bar of the download to stderr
    """
    return _resnet('resnet50', Bottleneck, [3, 4, 6, 3], pretrained, progress,
                   **kwargs)


def resnet101(pretrained=False, progress=True, **kwargs):
    r"""ResNet-101 model from
    `"Deep Residual Learning for Image Recognition" <https://arxiv.org/pdf/1512.03385.pdf>`_
    Args:
        pretrained (bool): If True, returns a model pre-trained on ImageNet
        progress (bool): If True, displays a progress bar of the download to stderr
    """
    return _resnet('resnet101', Bottleneck, [3, 4, 23, 3], pretrained, progress,
                   **kwargs)


def resnet152(pretrained=False, progress=True, **kwargs):
    r"""ResNet-152 model from
    `"Deep Residual Learning for Image Recognition" <https://arxiv.org/pdf/1512.03385.pdf>`_
    Args:
        pretrained (bool): If True, returns a model pre-trained on ImageNet
        progress (bool): If True, displays a progress bar of the download to stderr
    """
    return _resnet('resnet152', Bottleneck, [3, 8, 36, 3], pretrained, progress,
                   **kwargs)


def resnext50_32x4d(pretrained=False, progress=True, **kwargs):
    r"""ResNeXt-50 32x4d model from
    `"Aggregated Residual Transformation for Deep Neural Networks" <https://arxiv.org/pdf/1611.05431.pdf>`_
    Args:
        pretrained (bool): If True, returns a model pre-trained on ImageNet
        progress (bool): If True, displays a progress bar of the download to stderr
    """
    kwargs['groups'] = 32
    kwargs['width_per_group'] = 4
    return _resnet('resnext50_32x4d', Bottleneck, [3, 4, 6, 3],
                   pretrained, progress, **kwargs)


def resnext101_32x8d(pretrained=False, progress=True, **kwargs):
    r"""ResNeXt-101 32x8d model from
    `"Aggregated Residual Transformation for Deep Neural Networks" <https://arxiv.org/pdf/1611.05431.pdf>`_
    Args:
        pretrained (bool): If True, returns a model pre-trained on ImageNet
        progress (bool): If True, displays a progress bar of the download to stderr
    """
    kwargs['groups'] = 32
    kwargs['width_per_group'] = 8
    return _resnet('resnext101_32x8d', Bottleneck, [3, 4, 23, 3],
                   pretrained, progress, **kwargs)


def wide_resnet50_2(pretrained=False, progress=True, **kwargs):
    r"""Wide ResNet-50-2 model from
    `"Wide Residual Networks" <https://arxiv.org/pdf/1605.07146.pdf>`_
    The model is the same as ResNet except for the bottleneck number of channels
    which is twice larger in every block. The number of channels in outer 1x1
    convolutions is the same, e.g. last block in ResNet-50 has 2048-512-2048
    channels, and in Wide ResNet-50-2 has 2048-1024-2048.
    Args:
        pretrained (bool): If True, returns a model pre-trained on ImageNet
        progress (bool): If True, displays a progress bar of the download to stderr
    """
    kwargs['width_per_group'] = 64 * 2
    return _resnet('wide_resnet50_2', Bottleneck, [3, 4, 6, 3],
                   pretrained, progress, **kwargs)


def wide_resnet101_2(pretrained=False, progress=True, **kwargs):
    r"""Wide ResNet-101-2 model from
    `"Wide Residual Networks" <https://arxiv.org/pdf/1605.07146.pdf>`_
    The model is the same as ResNet except for the bottleneck number of channels
    which is twice larger in every block. The number of channels in outer 1x1
    convolutions is the same, e.g. last block in ResNet-50 has 2048-512-2048
    channels, and in Wide ResNet-50-2 has 2048-1024-2048.
    Args:
        pretrained (bool): If True, returns a model pre-trained on ImageNet
        progress (bool): If True, displays a progress bar of the download to stderr
    """
    kwargs['width_per_group'] = 64 * 2
    return _resnet('wide_resnet101_2', Bottleneck, [3, 4, 23, 3],
                   pretrained, progress, **kwargs)
