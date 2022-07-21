import torch
import random
import torch.multiprocessing as mp
import matplotlib.pyplot as plt
import torch.optim as optim
import torch.nn as nn
import numpy as np
from model import AE, UNET_AE, RNN, GRU, LSTM, Hybrid_MD_RNN_AE, resetPipeline
from utils_new import get_UNET_AE_loaders, get_RNN_loaders, losses2file, get_Hybrid_loaders
from plotting import compareAvgLoss, compareLossVsValid
from trial_1 import train_AE, valid_AE, error_timeline, get_latentspace_AE
from trial_2 import train_RNN, valid_RNN
from trial_5 import valid_HYBRID_Couette
from trial_6 import valid_HYBRID_KVS

torch.manual_seed(10)
random.seed(10)

try:
    mp.set_start_method('spawn')
except RuntimeError:
    pass

plt.style.use(['science'])
np.set_printoptions(precision=6)

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
NUM_WORKERS = 0


def trial_7_Hybrid_KVS_non_UNET(alpha, alpha_string, train_loaders, valid_loaders):
    """The trial_7_Hybrid_KVS_non_UNET function trains the given model on the KVS
    data distribution. It documents model progress via saving average training
    and validation losses to file and comparing them in a plot.

    Args:
        alpha:
          A double value indicating the chosen learning rate.
        alpha_string:
          Object of type string used as a model identifier.
        train_loaders:
          Object of PyTorch-type DataLoader to automatically pass training
          dataset to model.
        valid_loaders:
          Object of PyTorch-type DataLoader to automatically pass validation
          dataset to model.

    Returns:
        NONE:
          This function documents model progress by saving results to file and
          creating meaningful plots.
    """
    _criterion = nn.L1Loss()
    _file_prefix = '/home/lerdo/lerdo_HPC_Lab_Project/MD_U-Net/' + \
        '3_Constituent_Hybrid_approach/Results/7_Hybrid_KVS_non_UNET/'
    _model_identifier = f'LR{alpha_string}'
    print('Initializing AE model.')
    _model = AE(
        device=device,
        in_channels=3,
        out_channels=3,
        features=[4, 8, 16],
        activation=nn.ReLU(inplace=True)
    ).to(device)

    print('Initializing training parameters.')
    _scaler = torch.cuda.amp.GradScaler()
    _optimizer = optim.Adam(_model.parameters(), lr=alpha)
    _epoch_losses = []
    _epoch_valids = []

    print('Beginning training.')
    for epoch in range(150):
        _avg_loss = 0
        for _train_loader in train_loaders:
            _avg_loss += train_AE(
                loader=_train_loader,
                model=_model,
                optimizer=_optimizer,
                criterion=_criterion,
                scaler=_scaler,
                model_identifier=_model_identifier,
                current_epoch=epoch+1
            )
        _avg_loss = _avg_loss/len(train_loaders)
        print('------------------------------------------------------------')
        print(f'{_model_identifier} Training Epoch: {epoch+1} -> Averaged'
              f'Loader Loss: {_avg_loss:.3f}')
        _epoch_losses.append(_avg_loss)

        _avg_valid = 0
        for _valid_loader in valid_loaders:
            _avg_valid += valid_AE(
                loader=_valid_loader,
                model=_model,
                criterion=_criterion,
                model_identifier=_model_identifier
            )
        _avg_valid = _avg_valid/len(valid_loaders)
        print('------------------------------------------------------------')
        print(f'{_model_identifier} Validation -> Averaged Loader Loss:'
              f'{_avg_valid:.3f}')
        _epoch_valids.append(_avg_valid)

    losses2file(
        losses=_epoch_losses,
        file_name=f'{_file_prefix}Losses_AE_KVS_{_model_identifier}'
    )
    losses2file(
        losses=_epoch_valids,
        file_name=f'{_file_prefix}Valids_AE_KVS_{_model_identifier}'
    )

    compareLossVsValid(
        loss_files=[
            f'{_file_prefix}Losses_AE_KVS_{_model_identifier}.csv',
            f'{_file_prefix}Valids_AE_KVS_{_model_identifier}.csv'
        ],
        loss_labels=['Training', 'Validation'],
        file_prefix=_file_prefix,
        file_name=f'_AE_KVS_{_model_identifier}'
    )
    torch.save(
        _model.state_dict(),
        f'{_file_prefix}Model_AE_KVS_{_model_identifier}'
    )
    return


def trial_7_Hybrid_KVS_non_UNET_mp():
    """The trial_7_Hybrid_KVS_non_UNET_mp function is essentially a helper function to
    facilitate the training of the most promising AE model configurations
    from trial_1 on the basis of the KVS and Couette data distributions.

    Args:
        NONE

    Returns:
        NONE
    """
    print('Starting Trial 7: AE (KVS)')
    _t_loaders, _v_loaders = get_UNET_AE_loaders(
        data_distribution='get_KVS',
        batch_size=32,
        shuffle=True
    )

    _alphas = [0.0005, 0.0001, 0.00005, 0.00001, 0.000005, 0.000001]
    _alpha_strings = ['0_0005', '0_0001', '0_00005',
                      '0_00001', '0_000005', '0_000001']

    _processes = []

    for i in range(6):
        _p = mp.Process(
            target=trial_7_Hybrid_KVS_non_UNET,
            args=(_alphas[i], _alpha_strings[i],
                  _t_loaders, _v_loaders,)
        )
        _p.start()
        _processes.append(_p)
        print(f'Creating Process Number: {i+1}')

    for _process in _processes:
        _process.join()
        print('Joining Process')
    return


def trial_7_Hybrid_KVS_non_UNET_latentspace_helper():
    """The trial_7_Hybrid_KVS_non_UNET_latentspace_helper function contains the
    additional steps to create the model-specific latentspace. It loads an
    already trained model in model.eval() mode, loads the dataset loaders and
    calls the get_latentspace_AE function for each individual subdataset in the
    training and validation datasets.

    Args:
        NONE

    Returns:
        NONE:
    """
    print('Starting Trial 7: Get Latentspace (KVS)')
    _file_prefix = '/home/lerdo/lerdo_HPC_Lab_Project/MD_U-Net/' + \
        '3_Constituent_Hybrid_approach/Results/7_Hybrid_KVS_non_UNET/'
    _model = AE(
        device=device,
        in_channels=3,
        out_channels=3,
        features=[4, 8, 16],
        activation=torch.nn.ReLU(inplace=True)
    ).to(device)

    _model.load_state_dict(torch.load(
        f'{_file_prefix}Model_AE_KVS_LR0_0001'))
    _model.eval()

    _loader_1, _loader_2_ = get_UNET_AE_loaders(
        data_distribution='get_KVS',
        batch_size=1,
        shuffle=False
    )
    _loaders = _loader_1 + _loader_2_
    _out_directory = '/home/lerdo/lerdo_HPC_Lab_Project/Trainingdata/CleanKVS_AE_LS/Latentspace_Dataset'
    _out_file_names = [
        '_kvs_10K_NE',
        '_kvs_10K_NW',
        '_kvs_10K_SE',
        '_kvs_10K_SW',
        '_kvs_20K_NE',
        '_kvs_20K_NW',
        '_kvs_20K_SE',
        '_kvs_20K_SW',
        '_kvs_30K_NE',
        '_kvs_30K_NW',
        '_kvs_30K_SE',
        '_kvs_30K_SW',
        '_kvs_40K_NE',
        '_kvs_40K_NW',
        '_kvs_40K_SE',
        '_kvs_40K_SW',
    ]
    for idx, _loader in enumerate(_loaders):
        get_latentspace_AE(
            loader=_loader,
            model=_model,
            out_file_name=f'{_out_directory}{_out_file_names[idx]}'
        )


def trial_7_Hybrid_KVS_RNN(model, model_identifier, alpha, train_loaders, valid_loaders):
    """The trial_7_Hybrid_KVS_RNN function trains the given model and documents
    its progress via saving average training and validation losses to file and
    comparing them in a plot.

    Args:
        model:
          Object of PyTorch Module class, i.e. the model to be trained.
        model_identifier:
          A unique string to identify the model. Here, a combination of the
          learning rate (_alpha), num of RNN layers (_num_layers) and sequence
          length (_seq_length) is used.
        alpha:
          A double value indicating the chosen learning rate.
        train_loaders:
          Object of PyTorch-type DataLoader to automatically pass training
          dataset to model.
        valid_loaders:
          Object of PyTorch-type DataLoader to automatically pass validation
          dataset to model.

    Returns:
        NONE:
          This function documents model progress by saving results to file and
          creating meaningful plots.
    """
    _criterion = nn.L1Loss()
    _file_prefix = '/home/lerdo/lerdo_HPC_Lab_Project/MD_U-Net/' + \
        '3_Constituent_Hybrid_approach/Results/7_Hybrid_KVS_non_UNET/'

    print('Initializing training parameters.')
    _scaler = torch.cuda.amp.GradScaler()
    _optimizer = optim.Adam(model.parameters(), lr=alpha)
    _epoch_losses = []
    _epoch_valids = []

    print('Beginning training.')
    for epoch in range(150):
        _avg_loss = 0
        for _train_loader in train_loaders:
            _avg_loss += train_RNN(
                loader=_train_loader,
                model=model,
                optimizer=_optimizer,
                criterion=_criterion,
                scaler=_scaler,
                model_identifier=model_identifier,
                current_epoch=epoch+1
            )
        _avg_loss = _avg_loss/len(train_loaders)
        print('------------------------------------------------------------')
        print(
            f'{model_identifier} Training Epoch: {epoch+1}-> Averaged '
            f'Loader Loss: {_avg_loss:.3f}')

        _epoch_losses.append(_avg_loss)

        _avg_valid = 0
        for _valid_loader in valid_loaders:
            _avg_valid += valid_RNN(
                loader=_valid_loader,
                model=model,
                criterion=_criterion,
                model_identifier=model_identifier
            )
        _avg_valid = _avg_valid/len(valid_loaders)
        print('------------------------------------------------------------')
        print(f'{model_identifier} Validation -> Averaged '
              f'Loader Loss: {_avg_valid:.3f}')
        _epoch_valids.append(_avg_valid)

    losses2file(
        losses=_epoch_losses,
        file_name=f'{_file_prefix}Losses_{model_identifier}'
    )
    losses2file(
        losses=_epoch_valids,
        file_name=f'{_file_prefix}Valids_{model_identifier}'
    )

    compareAvgLoss(
        loss_files=[
            f'{_file_prefix}Losses_{model_identifier}.csv',
            f'{_file_prefix}Valids_{model_identifier}.csv'
        ],
        loss_labels=['Training', 'Validation'],
        file_prefix=_file_prefix,
        file_name=f'And_Valids_{model_identifier}'
    )
    torch.save(
        model.state_dict(),
        f'{_file_prefix}Model_{model_identifier}'
    )


def trial_7_Hybrid_KVS_RNN_mp():
    """The trial_7_Hybrid_KVS_RNN_mp function is essentially a helper function
    to facilitate the training of multiple concurrent models via multiprocessing
    of the trial_7_Hybrid_KVS_RNN function. Here, 3 unique models are trained using
    the most promising RNN/GRU/LSTM configurations from trials 2/3/4. Refer to
    the trial_7_Hybrid_KVS_RNN function for more details.

    Args:
        NONE

    Returns:
        NONE
    """
    print('Starting Trial 7: RNN_mp (KVS, AE)')
    _models = []
    _model_identifiers = [
        'KVS_AE_RNN_LR0_00001_Lay1_Seq25',
        'KVS_AE_GRU_LR0_00001_Lay2_Seq25',
        'KVS_AE_LSTM_LR0_00001_Lay2_Seq25',
    ]
    _alphas = [0.00001, 0.00001, 0.00001]

    _model_rnn_1 = RNN(
        input_size=256,
        hidden_size=256,
        seq_size=25,
        num_layers=1,
        device=device
    ).to(device)
    _models.append(_model_rnn_1)
    _model_rnn_2 = GRU(
        input_size=256,
        hidden_size=256,
        seq_size=25,
        num_layers=2,
        device=device
    ).to(device)
    _models.append(_model_rnn_2)
    _model_rnn_3 = LSTM(
        input_size=256,
        hidden_size=256,
        seq_size=25,
        num_layers=2,
        device=device
    ).to(device)
    _models.append(_model_rnn_3)

    _t_loader_25, _v_loader_25 = get_RNN_loaders(
        data_distribution="get_AE_KVS",
        batch_size=32,
        seq_length=25,
        shuffle=True
    )
    processes = []

    for i in range(3):
        p = mp.Process(
            target=trial_7_Hybrid_KVS_RNN,
            args=(_models[i], _model_identifiers[i], _alphas[i],
                  _t_loader_25, _v_loader_25,)
        )
        p.start()
        processes.append(p)
        print(f'Creating Process Number: {i+1}')

    for process in processes:
        process.join()
        print('Joining Process')


def trial_7_KVS_Hybrid(model_rnn, model_identifier, train_loaders, valid_loaders):
    """The trial_7_KVS_Hybrid function creates a Hybrid_MD_RNN_UNET model on the
    basis of a trained AE and a trained RNN/GRU/LSTM. It then documents
    its performance w.r.t. time series prediction, i.e. performance in
    accurately predicting the cell velocities for the next MD timestep. This is
    done as a proof of concept merley via terminal output. In addition, this
    function calls the valid_HYBRID_KVS function which automatically compares
    flow profiles of model prediction and corresponding target via the
    plotVelocityField function. Refer to valid_HYBRID_KVS for more details.

    Args:
        model_rnn:
          Object of PyTorch Module class, i.e. the RNN/GRU/LSTM model to be
          incorporated into the hybrid model.
        model_identifier:
          A unique string to identify the model. Here the RNN configuration is
          used to identify the RNN model (RNN-Type/LR0_XXXLayX_SeqXX)
        train_loaders:
          Object of PyTorch-type DataLoader to automatically pass training
          dataset to model.
        valid_loaders:
          Object of PyTorch-type DataLoader to automatically pass validation
          dataset to model.

    Returns:
        NONE:
          This function documents model progress by printing the average loss
          for each training and validation set to the terminal.
    """
    _criterion = nn.L1Loss()

    _model_AE = AE(
        device=device,
        in_channels=3,
        out_channels=3,
        features=[4, 8, 16],
        activation=nn.ReLU(inplace=True)
    )
    _model_AE.load_state_dict(torch.load(
        '/home/lerdo/lerdo_HPC_Lab_Project/MD_U-Net/3_Constituent_Hybrid_approach'
        '/Results/7_Hybrid_KVS_non_UNET/Model_AE_KVS_LR0_0001'))

    print('Initializing Hybrid_MD_RNN_UNET model.')
    _model_hybrid = Hybrid_MD_RNN_AE(
        device=device,
        AE_Model=_model_AE,
        RNN_Model=model_rnn,
        seq_length=25
    ).to(device)

    _counter = 0

    _train_loss = 0
    for _loader in train_loaders:
        _loss, _ = valid_HYBRID_KVS(
            loader=_loader,
            model=_model_hybrid,
            criterion=_criterion,
            model_identifier=model_identifier,
            dataset_identifier=str(_counter)
        )
        _train_loss += _loss
        resetPipeline(_model_hybrid)
        _counter += 1

    print('------------------------------------------------------------')
    print(f'{model_identifier} Training -> Averaged Loader Loss: '
          f'{_train_loss/len(train_loaders)}')

    _valid_loss = 0
    for _loader in valid_loaders:
        _loss, _ = valid_HYBRID_KVS(
            loader=_loader,
            model=_model_hybrid,
            criterion=_criterion,
            model_identifier=model_identifier,
            dataset_identifier=str(_counter)
        )
        _valid_loss += _loss
        resetPipeline(_model_hybrid)
        _counter += 1

    print('------------------------------------------------------------')
    print(f'{model_identifier} Validation -> Averaged Loader Loss: '
          f'{_valid_loss/len(valid_loaders)}')
    return


def trial_7_KVS_Hybrid_mp():
    """The trial_7_KVS_Hybrid_mp function is essentially a helper function to
    facilitate the validation of multiple concurrent models via multiprocessing
    of the trial_7_KVS_Hybrid function. Here, 3 unique models are validated using
    the best performing AE (pretrained) from trial_1 and the best performing
    RNN/GRU/LSTM (pretrained) models.

    Args:
        NONE

    Returns:
        NONE
    """
    print('Starting Trial 6: Hybrid MD RNN AE (KVS, AE)')
    _train_loaders, _valid_loaders = get_Hybrid_loaders(
        data_distribution='get_KVS',
        batch_size=1,
        shuffle=False
    )
    _models = []
    _model_identifiers = [
        'AE_RNN_LR0_00001_Lay1_Seq25',
        'AE_GRU_LR0_00001_Lay2_Seq25',
        'AE_LSTM_LR0_00001_Lay2_Seq25',
    ]

    _model_rnn_1 = RNN(
        input_size=256,
        hidden_size=256,
        seq_size=25,
        num_layers=1,
        device=device
    )
    _model_rnn_1.load_state_dict(torch.load(
        '/home/lerdo/lerdo_HPC_Lab_Project/MD_U-Net/3_Constituent_Hybrid_approach'
        '/Results/7_Hybrid_KVS_non_UNET/Model_KVS_AE_RNN_LR0_00001_Lay1_Seq25'))
    _models.append(_model_rnn_1)

    _model_rnn_2 = GRU(
        input_size=256,
        hidden_size=256,
        seq_size=25,
        num_layers=2,
        device=device
    )
    _model_rnn_2.load_state_dict(torch.load(
        '/home/lerdo/lerdo_HPC_Lab_Project/MD_U-Net/3_Constituent_Hybrid_approach'
        '/Results/7_Hybrid_KVS_non_UNET/Model_KVS_AE_GRU_LR0_00001_Lay2_Seq25'))
    _models.append(_model_rnn_2)

    _model_rnn_3 = LSTM(
        input_size=256,
        hidden_size=256,
        seq_size=25,
        num_layers=2,
        device=device
    )
    _model_rnn_3.load_state_dict(torch.load(
        '/home/lerdo/lerdo_HPC_Lab_Project/MD_U-Net/3_Constituent_Hybrid_approach'
        '/Results/7_Hybrid_KVS_non_UNET/Model_KVS_AE_LSTM_LR0_00001_Lay2_Seq25'))
    _models.append(_model_rnn_3)

    _processes = []
    for i in range(3):
        _p = mp.Process(
            target=trial_7_KVS_Hybrid,
            args=(_models[i], _model_identifiers[i],
                  _train_loaders, _valid_loaders,)
        )
        _p.start()
        _processes.append(_p)
        print(f'Creating Process Number: {i+1}')

    for _process in _processes:
        _process.join()
        print('Joining Process')
    return


if __name__ == "__main__":

    trial_7_KVS_Hybrid_mp()