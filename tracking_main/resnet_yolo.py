import torch
import torch.nn as nn
import torch.utils.model_zoo as model_zoo
import math
import torch.nn.functional as F


__all__ = ['ResNet', 'resnet18', 'resnet34', 'resnet50', 'resnet101', 'resnet152']


model_urls = {
    'resnet18': 'https://download.pytorch.org/models/resnet18-5c106cde.pth',
    'resnet34': 'https://download.pytorch.org/models/resnet34-333f7ec4.pth',
    'resnet50': 'https://download.pytorch.org/models/resnet50-19c8e357.pth',
    'resnet101': 'https://download.pytorch.org/models/resnet101-5d3b4d8f.pth',
    'resnet152': 'https://download.pytorch.org/models/resnet152-b121ed2d.pth',
}


def conv3x3(in_planes, out_planes, stride=1):
    return nn.Conv2d(in_planes, out_planes, kernel_size=3, stride=stride, padding=1, bias=False)


class BasicBlock(nn.Module):
    expansion = 1

    def __init__(self, inplanes, planes, stride=1, downsample=None):
        super(BasicBlock, self).__init__()
        self.conv1 = conv3x3(inplanes, planes, stride)
        self.bn1 = nn.BatchNorm2d(planes)
        self.relu = nn.ReLU(inplace=True)
        self.conv2 = conv3x3(planes, planes)
        self.bn2 = nn.BatchNorm2d(planes)
        self.downsample = downsample
        self.stride = stride

    def forward(self, x):
        residual = x

        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.bn2(out)

        if self.downsample is not None:
            residual = self.downsample(x)

        out += residual
        out = self.relu(out)

        return out


class Bottleneck(nn.Module):
    expansion = 4

    def __init__(self, inplanes, planes, stride=1, downsample=None):
        super(Bottleneck, self).__init__()
        self.conv1 = nn.Conv2d(inplanes, planes, kernel_size=1, bias=False)
        self.bn1 = nn.BatchNorm2d(planes)
        self.conv2 = nn.Conv2d(planes, planes, kernel_size=3, stride=stride, padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(planes)
        self.conv3 = nn.Conv2d(planes, planes * 4, kernel_size=1, bias=False)
        self.bn3 = nn.BatchNorm2d(planes * 4)
        self.relu = nn.ReLU(inplace=True)
        self.downsample = downsample
        self.stride = stride

    def forward(self, x):
        residual = x

        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.bn2(out)
        out = self.relu(out)

        out = self.conv3(out)
        out = self.bn3(out)

        if self.downsample is not None:
            residual = self.downsample(x)

        out += residual
        out = self.relu(out)

        return out


class DetNetBottleneck(nn.Module):
    expansion = 1

    def __init__(self, in_planes, planes, stride=1, block_type='A'):
        super(DetNetBottleneck, self).__init__()
        self.conv1 = nn.Conv2d(in_planes, planes, kernel_size=1, bias=False)
        self.bn1 = nn.BatchNorm2d(planes)
        self.conv2 = nn.Conv2d(planes, planes, kernel_size=3, stride=stride, padding=2, bias=False, dilation=2)
        self.bn2 = nn.BatchNorm2d(planes)
        self.conv3 = nn.Conv2d(planes, self.expansion*planes, kernel_size=1, bias=False)
        self.bn3 = nn.BatchNorm2d(self.expansion*planes)

        self.downsample = nn.Sequential()
        if stride != 1 or in_planes != self.expansion*planes or block_type == 'B':
            self.downsample = nn.Sequential(
                nn.Conv2d(in_planes, self.expansion*planes, kernel_size=1, stride=stride, bias=False),
                nn.BatchNorm2d(self.expansion*planes)
            )

    def forward(self, x):
        out = F.relu(self.bn1(self.conv1(x)))
        out = F.relu(self.bn2(self.conv2(out)))
        out = self.bn3(self.conv3(out))
        out += self.downsample(x)
        out = F.relu(out)
        return out


class ResNet(nn.Module):
    def __init__(self, block, layers):
        self.inplanes = 64
        super(ResNet, self).__init__()
        self.conv1 = nn.Conv2d(3, 64, kernel_size=7, stride=2, padding=3, bias=False)
        self.bn1 = nn.BatchNorm2d(64)
        self.relu = nn.ReLU(inplace=True)
        self.maxpool = nn.MaxPool2d(kernel_size=3, stride=2, padding=1)
        self.layer1 = self._make_layer(block, 64, layers[0])
        self.layer2 = self._make_layer(block, 128, layers[1], stride=2)
        self.layer3 = self._make_layer(block, 256, layers[2], stride=2)
        self.layer4 = self._make_layer(block, 512, layers[3], stride=2)
        self.layer5 = self._make_detnet_layer(in_channels=layers[4])
        self.avgpool = nn.AvgPool2d(2)  # fit 448 input size
        self.conv_end = nn.Conv2d(256, 10, kernel_size=3, stride=1, padding=1, bias=False)
        self.bn_end = nn.BatchNorm2d(10)
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.out_channels
                m.weight.data.normal_(0, math.sqrt(2. / n))
            elif isinstance(m, nn.BatchNorm2d):
                m.weight.data.fill_(1)
                m.bias.data.zero_()

    def _make_layer(self, block, planes, blocks, stride=1):
        downsample = None
        if stride != 1 or self.inplanes != planes * block.expansion:
            downsample = nn.Sequential(
                nn.Conv2d(self.inplanes, planes * block.expansion,
                          kernel_size=1, stride=stride, bias=False),
                nn.BatchNorm2d(planes * block.expansion),
            )

        layers = list()
        layers.append(block(self.inplanes, planes, stride, downsample))
        self.inplanes = planes * block.expansion
        for i in range(1, blocks):
            layers.append(block(self.inplanes, planes))

        return nn.Sequential(*layers)
    
    def _make_detnet_layer(self, in_channels):
        layers = list()
        layers.append(DetNetBottleneck(in_planes=in_channels, planes=256, block_type='B'))
        layers.append(DetNetBottleneck(in_planes=256, planes=256, block_type='A'))
        layers.append(DetNetBottleneck(in_planes=256, planes=256, block_type='A'))
        return nn.Sequential(*layers)

    def forward(self, x):
        x = self.conv1(x)
        x = self.bn1(x)
        x = self.relu(x)
        x = self.maxpool(x)

        x = self.layer1(x)
        x = self.layer2(x)
        x = self.layer3(x)
        x = self.layer4(x)
        x = self.layer5(x)
        #x = self.avgpool(x)
        x = self.conv_end(x)
        x = self.bn_end(x)
        x = torch.sigmoid(x)
        x = x.permute(0, 2, 3, 1)  # (-1,7,7,30)

        return x


def load_my_state_dict(net, parameter_url):
    param = model_zoo.load_url(model_urls[parameter_url])
    model_dict = net.state_dict()
    for name, param in param.items():
        if name not in model_dict:
            continue
        else:
            model_dict[name].copy_(param)


def resnet18(pretrained=False, use_gpu=False, **kwargs):
    model = ResNet(BasicBlock, [2, 2, 2, 2, 512], **kwargs)
    if pretrained:
        load_my_state_dict(model, 'resnet18')
    if use_gpu:
        return model.cuda()
    return model


def resnet34(pretrained=False, use_gpu=False, **kwargs):
    model = ResNet(BasicBlock, [3, 4, 6, 3, 512], **kwargs)
    if pretrained:
        load_my_state_dict(model, 'resnet34')
    if use_gpu:
        return model.cuda()
    return model


def resnet50(pretrained=False, use_gpu=False, **kwargs):
    model = ResNet(Bottleneck, [3, 4, 6, 3, 2048], **kwargs)
    if pretrained:
        load_my_state_dict(model, 'resnet50')
    if use_gpu:
        return model.cuda()
    return model


def resnet101(pretrained=False, use_gpu=False, **kwargs):
    model = ResNet(Bottleneck, [3, 4, 23, 3, 2048], **kwargs)
    if pretrained:
        load_my_state_dict(model, 'resnet101')
    if use_gpu:
        return model.cuda()
    return model


def resnet152(pretrained=False, use_gpu=False, **kwargs):
    model = ResNet(Bottleneck, [3, 8, 36, 3, 2048], **kwargs)
    if pretrained:
        load_my_state_dict(model, 'resnet152')
    if use_gpu:
        return model.cuda()
    return model


def test():
    net = resnet18(pretrained=False, use_gpu=True)
    load_my_state_dict(net, 'resnet18')
    img = torch.rand(10, 4, 448, 448).cuda()
    output = net(img).cpu()
    print(output.size())
    print(output[0, :, :, 4])


if __name__ == '__main__':
    test()
