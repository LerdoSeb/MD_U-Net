# from ptflops import get_model_complexity_info
# from torchsummary import summary
# import torchvision.transforms.functional as TF
import torch.nn as nn
import torch
import numpy as np

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
use_cuda = torch.cuda.is_available()

# This Pytorch implementation of the well-known U-Net architecture was presented
# by Aladdin Persson (YouTube, GitHub). The main idea is to first create the
# DoubleConv class, since this functionality is essentially repeated on every
# level of the U-Net (even on both sides). Next, by creating the U-Net class
# the left (contracting) side, the bottleneck and the right (expanding side) are
# implemented.

# The initial experiment shall make use of data generated by the analytical
# couette, since this can best be modified to resemble the data as presented in
# the original U-Net paper: 572x572 greyscale image. We shall opt for 64x64
# without noise for proof of concept.


def tensor_FIFO_pipe(tensor, x, device):
    return torch.cat((tensor[1:].to(device), x.to(device)))


class DoubleConv(nn.Module):
    # For the MaMiCo implementation consider reflective padding and leaky ReLu.
    # Also, consider revisting BatchNorm2d.
    def __init__(self, in_channels, out_channels, activation=nn.ReLU(inplace=True)):
        # PARAMETERS:
        # in_channels - channels contained in input data
        # out_channels - number of applied kernels -> channels contained in
        # output data
        super(DoubleConv, self).__init__()
        self.conv = nn.Sequential(
            nn.Conv3d(in_channels, out_channels, 3, 1, 1,
                      bias=False),
            # PARAMETERS:
            # 3: kernel_size
            # 1: stride
            # 1: padding -> same padding
            # nn.BatchNorm3d(out_channels),
            activation,
            nn.Conv3d(out_channels, out_channels, kernel_size=3,
                      stride=1, padding=1, bias=False),
            # nn.BatchNorm3d(out_channels),
            activation,
        )

    def forward(self, x):
        return self.conv(x)


class UNET_AE(nn.Module):
    def __init__(self, device, in_channels=3, out_channels=3, features=[4, 6, 8, 10], activation=nn.ReLU(inplace=True)):
        # PARAMETERS:
        # device - used to enable CUDA
        # in_channels - channels contained in input data
        # out_channels - channels to be contained in output data
        # features - corresponds to the number of applied kernels per convolution
        # activation - enables to freely choose desired activation function

        # Note that this model is concieved as an autoencoder to be used for
        # common MaMiCo spatial dimensions such as 24x24x24 (input and output).
        # With this, the input dimension is reduced via:
        # 24x24x24->12x12x12->6x6x6x->3x3x3.
        # The bottleneck signal is once more reduced to 2x2x2 for future use
        # in an RNN.

        # Moreover, this model will be trained as an autoencoder for later
        # integratin in a hybrid model. As such, training can only be
        # performed with a batch_size of 1.

        # XXXX Dimensions have not been approved. XXXX

        super(UNET_AE, self).__init__()
        self.device = device
        # U-Net building blocks
        self.ups = nn.ModuleList()
        self.downs = nn.ModuleList()
        self.pool = nn.MaxPool3d(kernel_size=2, stride=2)
        self.helper_down = nn.Conv3d(
            in_channels=16, out_channels=16, kernel_size=2, stride=1, padding=0, bias=False)
        self.activation = nn.ReLU()
        self.helper_up_1 = nn.ConvTranspose3d(
            in_channels=32, out_channels=32, kernel_size=2, stride=1, padding=0, bias=False)
        self.helper_up_2 = nn.Conv3d(
            in_channels=4, out_channels=3, kernel_size=3, stride=1, padding=1, bias=False)

        # Down part of UNET
        for feature in features:
            self.downs.append(DoubleConv(in_channels, feature, activation))
            in_channels = feature

        # Up part of UNET
        for feature in reversed(features):
            self.ups.append(
                nn.ConvTranspose3d(
                    feature*2, feature, kernel_size=2, stride=2,
                )
            )
            self.ups.append(DoubleConv(feature*2, feature, activation))

        # This is the "deepest" part.
        # self.bottleneck = DoubleConv(features[-1], features[-1]*2, activation)
        self.bottleneck = DoubleConv(features[-1], features[-1]*2, activation)
        print('Model initialized: UNET Autoencoder.')

    def forward(self, x, y=0, skip_connections=0):
        if y == 0 or y == 'get_bottleneck':
            # print('Size of x: ', x.size())
            skip_connections = []
            # The following for-loop describes the entire (left) contracting side,
            # including storing the skip-connections:
            for down in self.downs:
                x = down(x)
                # print('Size of x: ', x.size())
                skip_connections.append(x)
                x = self.pool(x)
                # print('Size of x: ', x.size())

            # This is the bottleneck
            # print("This is the bottleneck:")
            # print("Size of x before additional Conv3D: ", x.size())
            x = self.helper_down(x)
            # print("Size of x after additional Conv3D: ", x.size())
            x = self.activation(x)
            x = self.bottleneck(x)
            # print("Size of x after bottleneck: ", x.size())
            x = self.activation(x)

            if y == 'get_bottleneck':
                return x, skip_connections

            x = self.helper_up_1(x)
            # print("Size of x after helper_up_1: ", x.size())
            x = self.activation(x)
            skip_connections = skip_connections[::-1]

            # The following for-loop describes the entire (right) expanding side.
            for idx in range(0, len(self.ups), 2):
                x = self.ups[idx](x)
                skip_connection = skip_connections[idx//2]
                concat_skip = torch.cat((skip_connection, x), dim=1)
                x = self.ups[idx+1](concat_skip)
            # print("Size of x before downsizing to MD: ", x.size())
            # print("Size of x after expanding path: ", x.size())

            x = self.helper_up_2(x)
            # print("Size of x after helper_up2: ", x.size())
            # x = self.activation(x)

            # for i in range(2):
            #     x = self.helper_up_3(x)
            #     x = self.activation(x)
            return x

        if y == 'get_MD_output':
            x = self.helper_up_1(x)
            # print("Size of x after helper_up_1: ", x.size())
            x = self.activation(x)
            skip_connections = skip_connections[::-1]

            # The following for-loop describes the entire (right) expanding side.
            for idx in range(0, len(self.ups), 2):
                x = self.ups[idx](x)
                skip_connection = skip_connections[idx//2]
                concat_skip = torch.cat((skip_connection, x), dim=1)
                x = self.ups[idx+1](concat_skip)
            # print("Size of x before downsizing to MD: ", x.size())
            # print("Size of x after expanding path: ", x.size())

            x = self.helper_up_2(x)
            # print("Size of x after helper_up2: ", x.size())
            # x = self.activation(x)

            # for i in range(2):
            #     x = self.helper_up_3(x)
            #     x = self.activation(x)
            return x


class RNN(nn.Module):
    # input.shape = (batch_size, num_seq, input_size)
    # output.shape = (batch_size, 1, input_size)
    def __init__(self, input_size, hidden_size, seq_size, num_layers, device):
        super(RNN, self).__init__()
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.seq_size = seq_size
        self.num_layers = num_layers
        self.device = device
        self.rnn = nn.RNN(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True
        )
        self.fc = nn.Linear(self.hidden_size*self.seq_size, self.input_size)

    def forward(self, x):
        # Set initial hidden states(for RNN, GRU, LSTM)
        h0 = torch.zeros(self.num_layers, x.size(
            0), self.hidden_size).to(self.device)

        out, _ = self.rnn(x, h0)

        # Decode the hidden state of the last time step
        out = out.reshape(out.shape[0], -1)

        # Apply linear regressor to the last time step
        out = self.fc(out)
        return out


class GRU(nn.Module):
    # input.shape = (batch_size, num_seq, input_size)
    # output.shape = (batch_size, 1, input_size)
    def __init__(self, input_size, hidden_size, seq_size, num_layers, device):
        super(GRU, self).__init__()
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.seq_size = seq_size
        self.num_layers = num_layers
        self.device = device
        self.gru = nn.GRU(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True
        )
        self.fc = nn.Linear(self.hidden_size*self.seq_size, self.input_size)

    def forward(self, x):
        # Set initial hidden states(for RNN, GRU, LSTM)
        h0 = torch.zeros(self.num_layers, x.size(
            0), self.hidden_size).to(self.device)

        out, _ = self.gru(x, h0)

        # Decode the hidden state of the last time step
        out = out.reshape(out.shape[0], -1)

        # Apply linear regressor to the last time step
        out = self.fc(out)
        return out


class LSTM(nn.Module):
    # input.shape = (batch_size, num_seq, input_size)
    # output.shape = (batch_size, 1, input_size)
    def __init__(self, input_size, hidden_size, seq_size, num_layers, device):
        super(LSTM, self).__init__()
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.seq_size = seq_size
        self.num_layers = num_layers
        self.device = device
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True
        )
        self.fc = nn.Linear(hidden_size*self.seq_size, input_size)

    def forward(self, x):
        # Set initial hidden states(for RNN, GRU, LSTM)
        h0 = torch.zeros(self.num_layers, x.size(
            0), self.hidden_size).to(self.device)
        c0 = torch.zeros(self.num_layers, x.size(
            0), self.hidden_size).to(self.device)

        out, _ = self.lstm(x, (h0, c0))

        # Decode the hidden state of the last time step
        out = out.reshape(out.shape[0], -1)

        # Apply linear regressor to the last time step
        out = self.fc(out)
        return out


class Hybrid_MD_RNN_UNET(nn.Module):
    def __init__(self, device, UNET_Model, RNN_Model, seq_length):
        # PARAMETERS:
        super(Hybrid_MD_RNN_UNET, self).__init__()
        self.device = device
        self.unet = UNET_Model.eval()
        self.rnn = RNN_Model.eval()
        self.seq_length = seq_length
        self.sequence = torch.zeros(self.seq_length, 256)
        print('Model initialized: Hybrid_MD_RNN_UNET')

    def forward(self, x):

        # print('Size of initial input: ', x.size())
        x, skip_connections = self.unet(x, y='get_bottleneck')
        # print('Size of bottleneck: ', x.size())

        x_shape = x.shape
        self.sequence = tensor_FIFO_pipe(
            tensor=self.sequence,
            x=torch.reshape(x, (1, 256)),
            device=self.device).to(self.device)
        # print('Size of self.sequence: ', self.sequence.size())

        interim = torch.reshape(self.sequence, (1, self.seq_length, 256))
        x = self.rnn(interim)
        # print('Size of RNN Output: ', x.size())

        x = torch.reshape(x, x_shape)
        # print('Size of x after reshaping: ', x.size())

        x = self.unet(x, y='get_MD_output', skip_connections=skip_connections)
        # print('Size of x as final output: ', x.size())
        return x


def resetPipeline(model):
    shape = model.sequence.size()
    model.sequence = torch.zeros(shape)
    return


def test_forward_overloading():
    # BRIEF - This function aims to check UNET_AE's workaround
    # forward overloading. This functionality is vital in order
    # to train and save the model for hybrid use where a RNN
    # is used to pass a unique bottleneck value. This function
    # checks if the functionality yields identical tensors:
    # x_check_1 = model(x)
    # x_interim, skips = model(x, y=get_interim)
    # x_check_2 = model(x_interim,y=get_output, skips=skips)

    model = UNET_AE(
        device=device,
        in_channels=3,
        out_channels=3,
        features=[4, 8, 16],
        activation=nn.ReLU(inplace=True)
    )

    _x_in = torch.ones(1000, 3, 24, 24, 24)
    _x_out_1 = model(x=_x_in)

    _x_bottleneck, _skips = model(x=_x_in, y='get_bottleneck')

    _x_out_2 = model(x=_x_bottleneck, y='get_MD_output',
                     skip_connections=_skips)

    if torch.equal(_x_out_1, _x_out_2):
        print('Tensors are equal.')
    else:
        print('Tensors are not equal.')


if __name__ == "__main__":
    test_forward_overloading()
    pass
