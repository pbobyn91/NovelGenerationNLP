# TODO: investigate https://www.tensorflow.org/tutorials/text/text_generation

import numpy as np
import gensim
import pickle
import string
from itertools import islice

from unidecode import unidecode
from keras.callbacks import LambdaCallback
from keras.callbacks import ModelCheckpoint
from keras.layers.recurrent import LSTM
from keras.layers.embeddings import Embedding
from keras.layers.recurrent import GRU
from keras.layers import Dense, Activation
from keras.models import Sequential
from keras.utils.data_utils import get_file
from gensim.models import Word2Vec



EPOCHS = 80        # EPOCHS is the amount of times the model is trained
BATCH_SIZE = 256    # number of samples that will be propagated through the network
RNN_UNITS = 1024    # Number of RNN units

model_file = 'E:/NovelGenerationNLP/test_models/doyle_model.model'
grams_file = 'E:/NovelGenerationNLP/test_models/doyle_grams.txt'
chkpt_file = 'E:/NovelGenerationNLP/test_models/arthur-conan-doyle_model.ckpt'

word_model = Word2Vec.load(model_file)
with open(grams_file, "rb") as fp:
    grams = pickle.load(fp)

# limit input samples to a multiple of batch size
grams = grams[:BATCH_SIZE*round(len(grams)/BATCH_SIZE)]

pretrained_weights = word_model.wv.syn0
vocab_size, emdedding_size = pretrained_weights.shape
print('Result embedding shape:', pretrained_weights.shape)
print('Checking similar words:')
for word in ['holmes', 'mystery', 'gun', 'woman']:
    most_similar = ', '.join('%s (%.2f)' % (similar, dist) for similar, dist in word_model.most_similar(word)[:8])
    print('  %s -> %s' % (word, most_similar))


def word2idx(word):
    return word_model.wv.vocab[word].index


def idx2word(idx):
    return word_model.wv.index2word[idx]


gram_len = max(len(s) for s in grams)

print('\nMax length is: ', gram_len)
print('\nPreparing the data for LSTM...')
train_x = np.zeros([len(grams), gram_len], dtype=np.int32)
train_y = np.zeros([len(grams)], dtype=np.int32)
for i, sentence in enumerate(grams):
    for t, word in enumerate(sentence[:-1]):
        train_x[i, t] = word2idx(word)
    train_y[i] = word2idx(sentence[-1])
print('train_x shape:', train_x.shape)
print('train_y shape:', train_y.shape)

print('\nTraining LSTM...')
model = Sequential()
model.add(Embedding(input_dim=vocab_size, output_dim=emdedding_size, weights=[pretrained_weights]))
model.add(GRU(RNN_UNITS, return_sequences=False, recurrent_initializer='glorot_uniform'))
model.add(Dense(units=vocab_size))
model.add(Activation('softmax'))
model.compile(optimizer='adam', loss='sparse_categorical_crossentropy')


def sample(preds, temperature=1.0):
    if temperature <= 0:
        return np.argmax(preds)
    preds = np.asarray(preds).astype('float64')
    preds = np.log(preds) / temperature
    exp_preds = np.exp(preds)
    preds = exp_preds / np.sum(exp_preds)
    probas = np.random.multinomial(1, preds, 1)
    return np.argmax(probas)


def generate_next(text, num_generated=16):
    word_idxs = [word2idx(word) for word in text.lower().split()]
    for i in range(num_generated):
        prediction = model.predict(x=np.array(word_idxs))
        idx = sample(prediction[-1], temperature=0.7)
        word_idxs.append(idx)
    return ' '.join(idx2word(idx) for idx in word_idxs)


def on_epoch_end(epoch, _):
    print('\nGenerating text after epoch: %d' % epoch)
    texts = [
        'holmes',
        'watson',
        'gun',
        'war',
        'mystery',
        'murder',
        'woman'
    ]
    for text in texts:
        sample = generate_next(text)
        print('%s... -> %s' % (text, sample))


# Create a callback that saves the model's weights
model_callback = ModelCheckpoint(filepath=chkpt_file, save_weights_only=True, verbose=1)

model.fit(train_x, train_y,
          batch_size=BATCH_SIZE,
          epochs=EPOCHS,
          callbacks=[model_callback, LambdaCallback(on_epoch_end=on_epoch_end)])
