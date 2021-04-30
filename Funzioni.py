import tensorflow as tf
from tqdm import tqdm
from SpectralLayer import Spectral
from tensorflow.keras.layers import Dense
import os
import fnmatch
from pandas import DataFrame as df
import seaborn as sb
import matplotlib.pyplot as plt
import numpy as np
import pickle as pk

physical_devices = tf.config.list_physical_devices('GPU')
tf.config.experimental.set_memory_growth(physical_devices[0], True)
tf.config.experimental.set_synchronous_execution(False)

def Spectral_conf(size=2000,
                  is_base=True,
                  is_diag=True,
                  regularize=None,
                  is_bias=False,
                  activation=''):
    return {'units': size,
            'is_base_trainable': is_base,  # True means a trainable basis, False ow
            'is_diag_trainable': is_diag,  # True means a trainable eigenvalues, False ow
            'diag_regularizer': regularize,
            'use_bias': is_bias,  # True means a trainable bias, False ow
            'activation': activation
            }

def find(pattern, path):
    result = []
    for root, dirs, files in os.walk(path):
        for name in files:
            if fnmatch.fnmatch(name, pattern):
                result.append(os.path.join(root, name))
    return result

def Dense_conf(size=2000,
               use_bias=False,
               kernel_regularizer=None,
               activation=''):
    return {'units': size,
            'use_bias': use_bias,
            'kernel_regularizer': kernel_regularizer,
            'activation': activation
            }


def build_feedforward(model_config):
    """
    :param model_config: Guarda 'activation' e 'type'
    :return: modello compilato
    """
    model = tf.keras.Sequential()
    model.add(tf.keras.layers.Input(shape=784, dtype='float32'))
    if model_config['type'] == 'Spectral':
        model.add(Spectral(**Spectral_conf(activation=model_config['activation'])))
        model.add(Spectral(**Spectral_conf(size=10, activation='softmax')))
    elif model_config['type'] == 'Dense':
        model.add(Dense(**Dense_conf(activation=model_config['activation'])))
        model.add(Dense(**Dense_conf(size=10, activation='softmax')))
    elif model_config['type'] == 'Alternate':
        model.add(Spectral(**Spectral_conf(activation=model_config['activation'], is_base=False)))
        model.add(Spectral(**Spectral_conf(size=10, activation='softmax', is_base=False)))
    else:
        print("\nLayer type error\n")
        return -1

    model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=model_config['learn_rate']),
                  loss='sparse_categorical_crossentropy',
                  metrics=['accuracy'],
                  run_eagerly=False)
    return model


def load_dataset(name):
    if name == 'MNIST':
        datas = tf.keras.datasets.mnist
    elif name == 'Fashion-MNIST':
        datas = tf.keras.datasets.fashion_mnist
    else:
        print("\nDataset error\n")
        return -1

    (x_train, y_train), (x_test, y_test) = datas.load_data()
    x_train, x_test = x_train / 255.0, x_test / 255.0
    flat_train = np.reshape(x_train, [x_train.shape[0], 28 * 28])
    flat_test = np.reshape(x_test, [x_test.shape[0], 28 * 28])
    return (flat_train, y_train), (flat_test, y_test)

def saving_file(model_config, test_results):
    path_name = model_config['save_path'] + '\\Results\\'
    os.makedirs(path_name, exist_ok=True)
    path_file = path_name + model_config['result_file_name']

    if not os.path.isfile(path_file):
        ris_df = df(columns=['dataset', 'activ', "type", "percentiles", "val_accuracy"])
        ris_df = ris_df.append(
            {'dataset': model_config['dataset'],
             'activ': model_config['activation'],
             "type": model_config['type'],
             "percentiles": test_results['percentiles'],
             "val_accuracy": test_results['val_accuracy']},
            ignore_index=True)
        with open(path_file, 'wb') as file:
            pk.dump(ris_df, file)
            print('\nScritto\n')

    else:
        with open(path_file, 'rb') as file:
            ris_df = pk.load(file)
            ris_df = ris_df.append(
                                    {'dataset': model_config['dataset'],
                                     'activ': model_config['activation'],
                                     "type": model_config['type'],
                                    "percentiles": test_results['percentiles'],
                                     "val_accuracy": test_results['val_accuracy']},
                                    ignore_index=True)
        with open(path_file, 'wb') as file:
            pk.dump(ris_df, file)

def spectral_trim(model, x_test, y_test, model_config):
    percentiles = model_config['percentiles']
    results = {'percentiles': [], "val_accuracy": []}
    diag = model.layers[0].diag.numpy()
    abs_diag = np.abs(diag)
    thresholds = [np.percentile(abs_diag, q=perc) for perc in percentiles]
    for t, perc in tqdm(list(zip(thresholds, percentiles)), desc="  Removing the eigenvalues"):
        diag[abs_diag < t] = 0.0
        model.layers[0].diag.assign(diag)
        test_results = model.evaluate(x_test, y_test, batch_size=1000, verbose=0)
        # storing the results
        results['percentiles'].append(perc)
        results["val_accuracy"].append(test_results[1])

    return results

def dense_trimming(model, x_test, y_test, model_config):
    percentiles = model_config['percentiles']
    weights = model.layers[0].weights[0].numpy()
    connectivity = np.abs(weights).sum(axis=0)
    thresholds = [np.percentile(connectivity, q=perc) for perc in percentiles]
    results = {'percentiles': [], 'val_accuracy': []}

    for t, perc in tqdm(list(zip(thresholds, percentiles)), desc="  Removing the nodes"):
        weights[:, connectivity < t] = 0.0
        model.layers[0].weights[0].assign(weights)
        test_results = model.evaluate(x_test, y_test, batch_size=1000, verbose=0)
        # storing the results
        results['percentiles'].append(perc)
        results["val_accuracy"].append(test_results[1])


    return results

def alternate_trimming(model, model_config, flat_train, y_train, flat_test, y_test):

    percentiles = model_config['percentiles']
    results = {"percentiles": [], "val_accuracy": []}

    diag = model.layers[0].diag.numpy()
    abs_diag = np.abs(diag)
    thresholds = [np.percentile(abs_diag, q=perc) for perc in percentiles]

    for t, perc in tqdm(list(zip(thresholds, percentiles)), desc="  Removing the eigenvalues and train vectors"):

        diag[abs_diag < t] = 0.0
        hid_size = np.count_nonzero(diag)

        #Smaller Model
        new_model = tf.keras.Sequential()
        new_model.add(tf.keras.layers.Input(shape=784, dtype='float32'))
        new_model.add(Spectral(**Spectral_conf(size=hid_size, activation=model_config['activation'], is_base=True)))
        new_model.add(Spectral(**Spectral_conf(size=10, activation='softmax', is_base=True)))

        new_model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=model_config['learn_rate']),
                      loss='sparse_categorical_crossentropy',
                      metrics=['accuracy'],
                      run_eagerly=False)

        new_model.layers[0].diag.assign(diag[diag != 0.0])
        tmp_base = model.layers[0].base.numpy()
        new_model.layers[0].base.assign(tmp_base[:, diag != 0.0])

        new_model.layers[1].diag.assign(model.layers[1].diag)
        tmp_base = model.layers[1].base.numpy()
        new_model.layers[1].base.assign(tmp_base[diag != 0.0, :])

        new_model.fit(flat_train, y_train, verbose=0, batch_size=model_config['batch_size'], epochs=20)
        test_results = new_model.evaluate(flat_test, y_test, batch_size=1000, verbose=0)
        results['percentiles'].append(perc)
        results["val_accuracy"].append(test_results[1])
        new_model = []

    return results

def train_and_trim(model_config):
    (flat_train, y_train), (flat_test, y_test) = load_dataset(model_config['dataset'])
    model = build_feedforward(model_config)
    model.fit(flat_train, y_train, verbose=0, batch_size=model_config['batch_size'], epochs=model_config['epochs'])
    if model_config['type'] == 'Spectral':
        saving_file(model_config, spectral_trim(model, flat_test, y_test, model_config))
    if model_config['type'] == 'Dense':
        saving_file(model_config, dense_trimming(model, flat_test, y_test, model_config))
    if model_config['type'] == 'Alternate':
        saving_file(model_config, alternate_trimming(model, model_config, flat_train, y_train, flat_test, y_test))

def plot_based_on(dataset='MNIST',activation='tanh',fname ='result_dataframe.pk', lable_size=13, ticks_size=11, save_fig=True):
    path = find(fname, os.getcwd())

    with open(path[0], 'rb') as f:
        df = pk.load(f)

    dataset_mask = df['dataset'] == dataset
    activation_mask = df['activ'] == activation

    to_plot = df[dataset_mask & activation_mask]

    plt.figure(figsize=(5.5, 5))
    sb.lineplot(x="percentiles", y="val_accuracy",hue='type', palette={'Alternate':'green', 'Spectral':'blue', 'Dense':'orange'}, style="type",
                markers=True, dashes=False, ci="sd", data=plot_preprocess(to_plot))
    plt.title(dataset+' - Activation:'+ activation)
    lbl = {'fontsize': lable_size}
    tsz = {'fontsize': ticks_size}
    plt.xlabel('Percentile', **lbl)
    plt.xticks(**tsz)
    plt.yticks(**tsz)
    plt.ylabel('Val. Accuracy', **lbl)
    plt.legend(**lbl)

    if save_fig:
        folder = os.getcwd() + '\\Figures trimming\\' + dataset
        os.makedirs(folder, exist_ok=True)
        save_path = folder + '\\' + activation
        plt.savefig(save_path)

    plt.show()

def plot_preprocess(dati):
    dati = dati[['type', 'percentiles', 'val_accuracy']].reset_index(drop=True)
    ris = {"type": [], "percentiles": [], "val_accuracy": []}

    for i in range(len(dati)):
        ris["type"].extend([dati['type'][i]] * len(dati['val_accuracy'][i]))
        ris["percentiles"].extend(dati['percentiles'][i])
        ris["val_accuracy"].extend(dati['val_accuracy'][i])
    return ris

