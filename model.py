import torch
import torch.nn as nn
from drawing_board import save3D_RGBArray2File
import torchvision.transforms.functional as TF
from torchsummary import summary
from ptflops import get_model_complexity_info

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
            nn.BatchNorm3d(out_channels),
            activation,
            nn.Conv3d(out_channels, out_channels, kernel_size=3,
                      stride=1, padding=1, bias=False),
            nn.BatchNorm3d(out_channels),
            activation,
        )

    def forward(self, x):
        return self.conv(x)


class UNET(nn.Module):
    # First define the UNET model. For the MaMiCo implementation, consider
    # the proper amount of input channels as well as the proper spatial
    # dimensionality, such that the depth of the U-Net can be chosen accordingly.
    # Additionally, consider creating a "calculater" to determine the possible
    # depth.

    def __init__(
            self, in_channels=3, out_channels=3, features=[64, 128, 256, 512], activation=nn.ReLU(inplace=True)):
        # PARAMETERS:
        # in_channels - channels contained in input data
        # out_channels - channels to be contained in output data
        # features - corresponds to the number of applied kernels per convolution

        super(UNET, self).__init__()
        self.ups = nn.ModuleList()
        self.downs = nn.ModuleList()
        self.pool = nn.MaxPool3d(kernel_size=2, stride=2)
        # This creates special lists to store nn.Modules for the contracting and
        # expanding path. it is iterable.

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
        self.bottleneck = DoubleConv(features[-1], features[-1]*2, activation)

        # This is the model's output.
        self.final_conv = nn.Conv3d(
            features[0], out_channels, kernel_size=1, stride=1)

    def forward(self, x):
        # The forward method is an inherited method from the parent class
        # nn.Module and must be overriden. It defines the mechanics of the
        # neural network, i.e. what is performed on the input in order to
        # acquire the desired output.

        # The expanding path requires the so-called skip-connections from their
        # respective counter-part on the contracting path. For this we need the
        # following (list) container.
        skip_connections = []

        # The following for-loop describes the entire (left) contracting side,
        # including storing the skip-connections:
        for down in self.downs:
            x = down(x)
            skip_connections.append(x)
            x = self.pool(x)

        # This is the bottleneck
        x = self.bottleneck(x)
        skip_connections = skip_connections[::-1]

        # The following for-loop describes the entire (right) expanding side.
        # Notice how the index iterates in steps of 2. This is because the up
        # list contains two elements per heirarchical layer.
        for idx in range(0, len(self.ups), 2):
            x = self.ups[idx](x)
            skip_connection = skip_connections[idx//2]

            # if x.shape != skip_connection.shape:
            #    x = TF.resize(x, size=skip_connection.shape[2:])

            concat_skip = torch.cat((skip_connection, x), dim=1)
            x = self.ups[idx+1](concat_skip)

        return self.final_conv(x)


class RNN(nn.Module):
    # input.shape = (batch_size, num_seq, input_size)
    # output.shape = (batch_size, 1, input_size)
    def __init__(self, input_size, hidden_size, num_layers, device):
        super(RNN, self).__init__()
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.device = device
        self.sequence = torch.zeros(5, 512)
        self.rnn = nn.RNN(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True
        )
        self.fc = nn.Linear(self.hidden_size, self.input_size)

    def forward(self, x):
        # Set initial hidden states(for RNN, GRU, LSTM)
        h0 = torch.zeros(self.num_layers, x.size(
            0), self.hidden_size).to(self.device)

        # Set initial cell states (for LSTM)
        # c0 = torch.zeros(self.num_layers, x.size(0), self.hidden_size).to(device)
        # c0.shape =

        # Forward propagate RNN
        # print("Checking dimension of input data: ", x.shape)
        self.sequence = tensor_FIFO_pipe(
            self.sequence, x, self.device).to(self.device)
        x = torch.reshape(self.sequence, (1, 5, 512))
        out, _ = self.rnn(x, h0)

        # Decode the hidden state of the last time step
        out = out[:, -1, :]

        # Apply linear regressor to the last time step
        out = self.fc(out)
        out = torch.reshape(out, (1, 1, 512))
        return out


class GRU(nn.Module):
    # input.shape = (batch_size, num_seq, input_size)
    # output.shape = (batch_size, 1, input_size)
    def __init__(self, input_size, hidden_size, num_layers, device):
        super(GRU, self).__init__()
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.device = device
        self.gru = nn.GRU(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True
        )
        self.fc = nn.Linear(self.hidden_size, self.input_size)

    def forward(self, x):
        # Set initial hidden states(for RNN, GRU, LSTM)
        h0 = torch.zeros(self.num_layers, x.size(
            0), self.hidden_size).to(self.device)
        # h0.shape =

        # Set initial cell states (for LSTM)
        # c0 = torch.zeros(self.num_layers, x.size(0), self.hidden_size).to(device)
        # c0.shape =

        # Forward propagate RNN
        out, _ = self.gru(x, h0)
        # out.shape =

        # Decode the hidden state of the last time step
        out = out[:, -1, :]
        # out.shape =

        # Apply linear regressor to the last time step
        out = self.fc(out)
        # out.shape =
        return out


class LSTM(nn.Module):
    # input.shape = (batch_size, num_seq, input_size)
    # output.shape = (batch_size, 1, input_size)
    def __init__(self, input_size, hidden_size, num_layers, device):
        super(LSTM, self).__init__()
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.device = device
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True
        )
        self.fc = nn.Linear(hidden_size, input_size)

    def forward(self, x):
        h0 = torch.zeros(self.num_layers, x.size(
            0), self.hidden_size).to(self.device)
        c0 = torch.zeros(self.num_layers, x.size(
            0), self.hidden_size).to(self.device)
        out, _ = self.lstm(x, (h0, c0))
        out = out[:, -1, :]
        return self.fc(out)


class INTERIM_MD_UNET(nn.Module):
    def __init__(self, device, in_channels=3, out_channels=3, features=[4, 6, 8, 10], activation=nn.ReLU(inplace=True), RNN_in_size=512, RNN_hid_size=1024, RNN_lay=2):
        # PARAMETERS:
        # in_channels - channels contained in input data
        # out_channels - channels to be contained in output data
        # features - corresponds to the number of applied kernels per convolution
        # activation - enables to freely choose desired activation function
        # RNN_in_size - corresponds to the number of input features in RNN
        # RNN_hid_size - coresponds to the number of perceptrons in hidden layer
        # RNN_lay - corresponds to the number of hidden layers
        # device - used to enable CUDA

        # Note that this hybrid model was concieved to be used for common MaMiCo
        # spatial dimensions such as 18 x 18 x 18. With this, the input dimension
        # is reduced via 18x18x18 -> 9x9x9 -> 4x4x4 -> 2x2x2. The bottleneck
        # signal is unrolled and passed to the RNN (multivariate LSTM model).

        # For the initial proof of concept trials we will consider the dimensions
        # 32x32x32 -> 16x16x16 -> 8x8x8 -> 4x4x4 -> 2x2x2 AND -> batchsize = 8

        super(INTERIM_MD_UNET, self).__init__()
        self.device = device
        self.ups = nn.ModuleList()
        self.downs = nn.ModuleList()
        self.pool = nn.MaxPool3d(kernel_size=2, stride=2)
        self.rnn = RNN(
            input_size=512,
            hidden_size=1024,
            num_layers=RNN_lay,
            device=device)

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

        # This is the model's output.
        self.final_conv = nn.Conv3d(
            features[0], out_channels, kernel_size=1, stride=1)

    def forward(self, x):

        skip_connections = []

        # The following for-loop describes the entire (left) contracting side,
        # including storing the skip-connections:
        for down in self.downs:
            x = down(x)
            skip_connections.append(x)
            x = self.pool(x)

        # This is the bottleneck
        x = self.bottleneck(x)

        # Extract the latent space and sanity check dimensions
        latent_space = x.to(self.device)
        print('Class-1-Latent Space shape: ', latent_space.size())

        # Reshape latent space and sanity check dimensions
        latent_space = torch.flatten(latent_space, start_dim=1).to(self.device)
        print('Class-2-Latent Space shape: ', latent_space.size())

        # Create RNN input and sanity check dimensions
        sequenceInput = torch.reshape(
            latent_space, (1, 512)).to(self.device)
        print('Class-4-SequenceInput shape: ', sequenceInput.size())

        # Apply RNN and sanity check output dimensions
        rnnOutput = self.rnn(sequenceInput).to(self.device)
        print('Class-5-rnnOutput shape: ', rnnOutput.size())

        # Merge output into CNN signal (->x) and sanity check dimensions
        x = torch.reshape(rnnOutput, (1, 64, 2, 2, 2))
        print('Class-6-CNN signal shape: ', x.size())

        skip_connections = skip_connections[::-1]

        # The following for-loop describes the entire (right) expanding side.
        for idx in range(0, len(self.ups), 2):
            x = self.ups[idx](x)
            skip_connection = skip_connections[idx//2]
            concat_skip = torch.cat((skip_connection, x), dim=1)
            x = self.ups[idx+1](concat_skip)

        return self.final_conv(x)


def test():

    # model = LSTM_MD_UNET(in_channels=3, out_channels=3, features=[4, 6, 8, 10])
    # model = UNET(in_channels=3, out_channels=3, features=[64, 128, 256, 512])
    # macs, params = get_model_complexity_info(
    #     model, (3, 32, 32, 32), as_strings=True, print_per_layer_stat=True, verbose=True)
    # print('{:<30}  {:<8}'.format('Computational complexity: ', macs))
    # print('{:<30}  {:<8}'.format('Number of parameters: ', params))
    model = INTERIM_MD_UNET(
        device=device,
        in_channels=3,
        out_channels=3,
        features=[4, 8, 16, 32],
        activation=nn.ReLU(inplace=True),
        RNN_in_size=512,
        RNN_hid_size=1024,
        RNN_lay=2
    ).to(device)
    x = torch.randn(1, 3, 32, 32, 32)
    preds = model(x)
    print('Test-Prediction shape: ', preds.size())
    # save3D_RGBArray2File(
    #    latent_space.cpu().detach().numpy(), "latent_space_test")
    # summary(model, input_size=80)
    # preds = model(x)
    # assert preds.shape == x.shape


if __name__ == "__main__":
    test()
    pass
