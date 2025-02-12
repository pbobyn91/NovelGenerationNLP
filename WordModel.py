"""
Core processing for a Word Model using Gensim Word2Vec and TensorFlow RNN.
"""

import pickle
import json
import textwrap
from itertools import islice
from time import time

import numpy as np
import spacy
from gensim.models import Word2Vec
from gensim.models.phrases import Phrases, Phraser
from keras.callbacks import LambdaCallback
from keras.callbacks import ModelCheckpoint
from keras.layers import Dense, Activation
from keras.layers.embeddings import Embedding
from keras.layers.recurrent import GRU
from keras.layers.recurrent import LSTM
from keras.models import Sequential
from keras.models import model_from_json
from unidecode import unidecode

from corpus import Corpus


class WordModel:
    """
    Contains all data and methods for developing and using a Word Model.
    """

    def __init__(self, model_name, model_dir, sim_words):
        """
        Initialize a Word Model with a name, file directory, and a list of seed words.

        :param model_name: The name of the model.
        :param model_dir: The directory where the model's files will be stored.
        :param sim_words: A list of words that appear in the model's corpus, to be used as seeds.
        """

        self.model_name = model_name
        self.model_dir = model_dir


        self.nlp = None
        self.phraser = None
        # A list of gram-sentences used as a dataset for the Word2Vec and machine learning models
        self.grams = None
        # The Word2Vec model that will generate word vectors
        self.w2v = None

        # The machine learning model that will predict words and generate text
        self.model = None
        # A list of words to check similarities / test training output with
        self.sim_words = sim_words

    def w2v_grams_from_file(self, gram_file):
        """
        Load in a list of grams from a pickled file.

        :param gram_file: The target file path.
        """

        with open(gram_file, "rb") as fp:
            self.grams = pickle.load(fp)

    def w2v_model_from_file(self, model_file):
        """
        Load in a Word2Vec model from a binary file.

        :param model_file: The target file path.
        """

        self.w2v = Word2Vec.load(model_file)

    def gen_model_from_file(self, model_file):
        """
        Load in a TensorFlow model architecture from a json file.

        :param model_file: The target file path.
        """

        with open(model_file, 'r') as file:
            json_config = file.read()

        self.model = model_from_json(json_config)

    def gen_load_checkpoint(self, checkpoint_file):
        """
        Load weights into the TensorFlow model from a checkpoint file.

        :param checkpoint_file: The target file path.
        """

        self.model.load_weights(checkpoint_file)

    def w2v_grams_to_file(self, custom_dir: str = None, custom_name: str = None):
        """
        Save the Word2Vec model's list of grams to a pickled file.

        :param custom_dir: Optional: A custom target directory.
        :param custom_name: Optional: A custom file name.
        """

        if custom_dir:
            dir = custom_dir
        elif self.model_dir:
            dir = self.model_dir
        else:
            raise ValueError("Must define a model directory")

        if custom_name:
            name = custom_name
        elif self.model_name:
            name = self.model_name
        else:
            raise ValueError("Must define a model name")

        if not self.grams:
            raise NameError("No grams to export")

        with open('{}{}_grams.txt'.format(dir, name), 'wb') as fp:
            pickle.dump(self.grams, fp)

    def w2v_model_to_file(self, custom_dir: str = None, custom_name: str = None, sep_limit: int = 10 * 1024**2):
        """
        Save the Word2Vec model to a binary file.

        :param custom_dir: Optional: A custom target directory.
        :param custom_name: Optional: A custom file name.
        :param sep_limit: Array separation limit, in bytes.
        """

        if custom_dir:
            dir = custom_dir
        elif self.model_dir:
            dir = self.model_dir
        else:
            raise ValueError("Must define a model directory")

        if custom_name:
            name = custom_name
        elif self.model_name:
            name = self.model_name
        else:
            raise ValueError("Must define a model name")

        if not self.w2v:
            raise NameError("No w2v model to export")

        self.w2v.save('{}{}_model.model'.format(dir, name), sep_limit=sep_limit)

    def w2v_grams(self, corpus_file: str = './data/corpus_directory.json', corpus_dir: str = './data/corpus/',
                  author: str = None, genre: str = None, log: bool = True, sentence_len: int = 40,
                  sentence_offset: int = 5, phrase_min_count: int = 20, phrase_threshold: int = 2, ):
        """
        Create a nested list of grams (words and word-pairs) from a corpus.

        :param corpus_file: A path to the Corpus Directory json file.
        :param corpus_dir: A path to the directory of the text files that make up the corpus.
        :param author: The full name of the desired author. For example: "Arthur Conan Doyle".
        :param genre: The desired genre or tag. For example: "fantasy".
        :param log: If true, prints process text to console.
        :param sentence_len: The desired length of the gram lists.
        :param sentence_offset: The desired offset for list staggering.
        :param phrase_min_count: Word-pairs that appear more times than this may be considered n-grams.
        :param phrase_threshold: Words and word-pairs that appear fewer times than this will be excluded.
        """

        # Check if arguments make sense
        if author and genre:
            raise ValueError("Cannot define both author and genre.")
        if not (author or genre):
            raise ValueError("Must define either author or genre")

        t = time()

        if author:
            docs = Corpus(corpus_file, corpus_dir).author_combined_string(author)
        else:
            docs = Corpus(corpus_file, corpus_dir).tag_combined_string(genre)

        if log:
            # Print out sample lines of unaltered input text
            print("Raw samples: ")
            print(docs[:sentence_len * 2], '...')
            print(docs[sentence_len * 2:sentence_len * 4], '...')
            print(docs[sentence_len * 4:sentence_len * 6], '...')

        if log:
            print("\n== CLEANING ==")

        # Further cleaning, lower-casing and removal of punctuation
        # (except for periods, exclamation and question points, and apostrophes)
        sent_clean = docs.lower().translate(str.maketrans('', '', '~@#$%^&*()+=_",/\\:;{}[]<>')).rstrip()
        sent_clean = sent_clean.replace('\n', ' ').replace('-', ' ')

        if log:
            # Print out samples of cleaned and formatted text
            print("Cleaned samples: ")
            print(sent_clean[:sentence_len * 2], '...')
            print(sent_clean[sentence_len * 2:sentence_len * 4], '...')
            print(sent_clean[sentence_len * 4:sentence_len * 6], '...')

        if log:
            print("\n== LEMMATIZING ==")

        self._w2v_load_spacy()

        # Temporarily split the text into very large sections, to prevent overloading spacy
        sent_lemma_temp = [self._w2v_lemmatize(doc) for doc in textwrap.wrap(sent_clean, 100000)]
        sent_lemma = ''.join(sent_lemma_temp)

        if log:
            print('Time to lemmatize: {} min'.format(round((time() - t) / 60, 2)))
        t = time()

        if log:
            # Print out samples of lemmatized text
            print("Lemmatized samples: ")
            print(sent_lemma[:sentence_len * 2], '...')
            print(sent_lemma[sentence_len * 2:sentence_len * 4], '...')
            print(sent_lemma[sentence_len * 4:sentence_len * 6], '...')

        if log:
            print("\n== GRAMMATIZING ==")

        sent_split = sent_lemma.split()

        # Create double-chunked list of split text to feed into Phraser
        sent_split_temp = list(self._chunks(sent_split, sentence_len)) + list(
            self._chunks(sent_split[int(sentence_len / 2):], sentence_len))

        # Ngram assignment
        phrases = Phrases(sent_split_temp, min_count=phrase_min_count, progress_per=10000,
                          threshold=phrase_threshold)
        bigram = Phraser(phrases)

        self.phraser = bigram

        # Trim ngram sentence length and remove empty lists
        sent_gram = bigram[sent_split]

        sent_arr_gram = []

        offset = 0
        # Final chunking of sentence list
        for i in range(int(sentence_len/sentence_offset)):
            if log:
                print("Chunking loop={} offset={} next{}words={}".format(i, offset, sentence_offset+1,
                                                                         sent_gram[offset:offset+sentence_offset+1]))
            sent_arr_gram += list(self._chunks(sent_gram[offset:], sentence_len))
            offset += sentence_offset

        # sent_arr_gram = list(self._chunks(sent_gram, sentence_len))

        self.grams = sent_arr_gram

        if log:
            # Print out samples of n-grammed text
            print("\nChunked samples: ")
            for line in islice(sent_arr_gram, 0, 3):
                print(line)

        if log:
            print('Time to grammatize: {} min'.format(round((time() - t) / 60, 2)))

    def w2v_seeds(self, text: list, log: bool = True, save: bool = True):
        """
        Create a list of seeds for this model, given a list of strings.

        :param text: The strings to convert to seeds.
        :param log: If true, prints process text to console.
        :param save: If true, saves the seeds to a file determined by the model parameters.
        :return: Returns a list of seeds strings.
        """

        t = time()

        docs = [unidecode(doc) for doc in text]

        if log:
            # Print out sample lines of unaltered input text
            print("\nRaw lines: ")
            for line in docs:
                print(line)

        # Further cleaning, lower-casing and removal of punctuation
        # (except for periods, exclamation and question points, and apostrophes)
        sent_clean = [doc.lower().translate(str.maketrans('', '', '~@#$%^&*()+=_",/\\:;{}[]<>')).rstrip() for doc in docs]
        sent_clean = [doc.replace('\n', ' ').replace('-', ' ') for doc in sent_clean]

        if log:
            # Print out samples of cleaned and formatted text
            print("\nCleaned lines: ")
            for line in sent_clean:
                print(line)

        self._w2v_load_spacy()

        sent_lemma = [self._w2v_lemmatize(doc) for doc in sent_clean]

        if log:
            print('\nTime to lemmatize: {} min'.format(round((time() - t) / 60, 2)))
        t = time()

        if log:
            # Print out samples of lemmatized text
            print("Lemmatized samples: ")
            for line in sent_lemma:
                print(line)

        sent_split = [doc.split() for doc in sent_lemma]

        # Trim ngram sentence length and remove empty lists
        sent_gram = [self.phraser[doc] for doc in sent_split]

        if log:
            # Print out samples of n-grammed text
            print("\nN-gram samples: ")
            for line in sent_gram:
                print(line)

        if log:
            print('Time to grammatize: {} min'.format(round((time() - t) / 60, 2)))

        if save:
            seed_file = '{}{}_seeds.txt'.format(self.model_dir, self.model_name)
            with open(seed_file, 'w') as f:
                for line in sent_gram:
                    out = ''
                    for word in line:
                        out += word + ' '
                    out += '\n'
                    f.write(out)

        return sent_gram

    def w2v_train(self, log: bool = True, min_count: int = 1, window: int = 2, sample: float = 6e-5,
                  alpha: float = 0.03, min_alpha: float = 0.0007, negative: int = 20, workers: int = 4):
        """
        Train the Word2Vec model.

        :param log: If true, prints process text to log.
        :param min_count: Grams that appear fewer times than this will not be vectorized.
        :param window: Size of the context-window - determines size of the model.
        :param sample: Random downsampling threshold.
        :param alpha: The initial learning rate.
        :param min_alpha: The minimum learning rate to pursue in training.
        :param negative: How many noise words to use for negative sampling.
        :param workers: Number of worker threads.
        """

        t = time()

        w2v_model = Word2Vec(min_count=min_count, window=window, size=300, sample=sample, alpha=alpha,
                             min_alpha=min_alpha, negative=negative, workers=workers)

        w2v_model.build_vocab(self.grams, progress_per=10000)

        if log:
            print('Time to build vocab: {} mins'.format(round((time() - t) / 60, 2)))
        t = time()

        w2v_model.train(self.grams, total_examples=w2v_model.corpus_count, epochs=30, report_delay=1)

        if log:
            print('Time to train the model: {} mins'.format(round((time() - t) / 60, 2)))

        # if self.model_name:
        #     w2v_model.save('{}{}_model.model'.format(self.model_dir, self.model_name))

        w2v_model.init_sims(replace=True)

        self.w2v = w2v_model

        if log:
            self._w2v_word_similarities(8)

    def gen_train(self, epochs: int = 40, batch_size: int = 256, rnn_units: int = 1024,
                  recurrent_initializer: str = 'glorot_uniform', log: bool = True, activation: str = 'softmax',
                  optimizer: str = 'adam', loss_algorithm: str = 'sparse_categorical_crossentropy'):
        """
        Train the Sequential model.

        :param epochs: How many training cycles (epochs) to train for.
        :param batch_size: The size of training batches.
        :param rnn_units: How many cells to use in the RNN (LSTM/GRU) layer.
        :param recurrent_initializer: Name of initializer for the recurrent-kernel weights matrix.
        :param log: If true, prints process text to console.
        :param activation: Name of activation function.
        :param optimizer: Name of optimization instance.
        :param loss_algorithm: Name of loss algorithm.
        """

        # limit input samples to a multiple of batch size
        grams = self.grams[:batch_size * round(len(self.grams) / batch_size)]

        pretrained_weights = self.w2v.wv.syn0
        vocab_size, embedding_size = pretrained_weights.shape

        if log:
            print('Result embedding shape:', pretrained_weights.shape)
            print('Checking similar words:')
            self._w2v_word_similarities(8)

        gram_len = max(len(s) for s in grams)

        print('\nMax length is: ', gram_len)
        print('Preparing the data for LSTM...')
        train_x = np.zeros([len(grams), gram_len], dtype=np.int32)
        train_y = np.zeros([len(grams)], dtype=np.int32)
        for i, sentence in enumerate(grams):
            for t, word in enumerate(sentence[:-1]):
                train_x[i, t] = self._gen_word2idx(word)
            train_y[i] = self._gen_word2idx(sentence[-1])

        print('train_x shape:', train_x.shape)
        print('train_y shape:', train_y.shape)

        for ex, ey in zip(train_x[:3], train_y[:3]):
            print("X: {}".format([self._gen_idx2word(idx) for idx in ex]))
            print("Y: {}".format(self._gen_idx2word(ey)))

        print('\nTraining LSTM...')
        model = Sequential()
        model.add(Embedding(input_dim=vocab_size, output_dim=embedding_size, weights=[pretrained_weights]))
        model.add(LSTM(rnn_units, return_sequences=False, recurrent_initializer=recurrent_initializer))
        model.add(Dense(units=vocab_size))
        model.add(Activation(activation))
        model.compile(optimizer=optimizer, loss=loss_algorithm)

        print(model.summary())
        json_config = model.to_json()
        # print(json_config)

        with open('{}{}_model.json'.format(self.model_dir, self.model_name), 'w') as file:
            file.write(json_config)

        self.model = model

        # "callbacks" being a list of functions
        # Create a callback that generates sample output
        callbacks = [LambdaCallback(on_epoch_end=self._gen_on_epoch_end)]

        # https://www.tensorflow.org/tutorials/keras/save_and_load#save_checkpoints_during_training
        if self.model_name and self.model_dir:
            # Create a callback that saves the model's weights
            ckpt_file = '{}{}_model.ckpt'.format(self.model_dir, self.model_name)
            callbacks.append(ModelCheckpoint(filepath=ckpt_file, save_weights_only=True, verbose=1))

        self.model.fit(train_x, train_y, batch_size=batch_size, epochs=epochs, callbacks=callbacks)

    def _w2v_load_spacy(self):
        """
        Load the appropriate spacy package.

        :return:
        """

        # Ensuring correct model is loaded in
        if spacy.util.is_package('en'):
            self.nlp = spacy.load('en', disable=['ner', 'parser'])
        elif spacy.util.is_package('en_core_web_sm'):
            self.nlp = spacy.load('en_core_web_sm', disable=['ner', 'parser'])
        else:
            return False
        return True

    def _w2v_lemmatize(self, doc):
        """
        Lemmatize a string. Cuts plurals and most conjugations.

        :param doc: The string to be lemmatized.
        :return: The lemmatized string.
        """
        # Begin lemmatization and removing stopwords - keeping pronouns and "be" conjugations
        # txt = [token.lemma_ for token in self.nlp(doc)]

        txt = []

        for token in self.nlp(doc):
            if token.lemma_ == '-PRON-':
                pron = self._w2v_pron(token.lower_)
                if pron:
                    txt.append(pron)
            elif token.lemma_ == 'be':
                be = self._w2v_be(token.lower_)
                if be:
                    txt.append(be)
            else:
                txt.append(token.lemma_)

        # Remove any sentence of two words or less
        if len(txt) > 2:
            return ' '.join(txt)

    @staticmethod
    def _w2v_pron(text):
        """
        Given a pronoun, returns the same or equivalent pronoun from a restricted set.

        :param text: The given pronoun.
        :return: The equivalent pronoun, or none, if no pronoun was given.
        """

        if text in ['i']:
            return 'i'
        elif text in ['me', 'myself']:
            return 'me'
        elif text in ['my', 'mine']:
            return 'my'
        elif text in ['you', 'yourself']:
            return 'you'
        elif text in ['your', 'yours']:
            return 'your'
        elif text in ['he']:
            return 'he'
        elif text in ['him', 'himself']:
            return 'himself'
        elif text in ['his']:
            return 'his'
        elif text in ['she']:
            return 'she'
        elif text in ['her', 'herself']:
            return 'her'
        elif text in ['hers']:
            return 'hers'
        elif text in ['it', 'itself']:
            return 'it'
        elif text in ['its']:
            return 'its'
        elif text in ['we']:
            return 'we'
        elif text in ['us', 'ourselves']:
            return 'us'
        elif text in ['ours']:
            return 'ours'
        elif text in ['they']:
            return 'they'
        elif text in ['them', 'themselves']:
            return 'them'
        elif text in ['their', 'theirs']:
            return 'their'
        else:
            return None

    @staticmethod
    def _w2v_be(text):
        """
        Given a conjugation of "be", returns the same or equivalent conjugation from a restricted set.

        :param text: The given conjugation.
        :return: The equivalent conjugation, or none, if no conjugation was given.
        """

        if text in ['be']:
            return 'be'
        if text in ['am']:
            return 'am'
        elif text in ['is']:
            return 'is'
        elif text in ['are']:
            return 'are'
        elif text in ['was']:
            return 'was'
        elif text in ['were']:
            return 'were'
        elif text in ['been']:
            return 'been'
        elif text in ['being']:
            return 'being'
        else:
            return None

    def _w2v_word_similarities(self, len: int, custom_words: list = None):
        """
        Given the model's sim-word list, print out similar words.

        :param len: The number of similar words to display.
        :param custom_words: Optional: A custom list of words.
        """

        if custom_words:
            # TODO: Custom words not yet implemented
            pass

        for word in self.sim_words:
            most_similar = ', '.join(
                '%s (%.2f)' % (similar, dist) for similar, dist in self.w2v.most_similar(word)[:len])
            print('  %s -> %s' % (word, most_similar))

    @staticmethod
    def _chunks(lst, n):
        """
        Yield successive n-sized chunks from lst.
        Returns a generator - use list() to decompose.

        See: https://stackoverflow.com/questions/312443/how-do-you-split-a-list-into-evenly-sized-chunks

        :param lst: The list to be chunked.
        :param n: The chunk size.
        :return: A generator containing the chunked lists.
        """

        for i in range(0, len(lst), n):
            yield lst[i:i + n]

    def _gen_word2idx(self, word):
        """
        Convert a word string to Word2Vec vocabulary index.

        :param word: The word to convert.
        :return: The given word's index.
        """
        return self.w2v.wv.vocab[word].index

    def _gen_idx2word(self, idx):
        """
        Convert a Word2Vec vocabulary index to a word string.

        :param idx: The index to convert.
        :return: The word string for the given index.
        """
        return self.w2v.wv.index2word[idx]

    @staticmethod
    def _gen_sample(preds, temperature=1.0):
        """"""
        if temperature <= 0:
            return np.argmax(preds)
        preds = np.asarray(preds).astype('float64')
        preds = np.log(preds) / temperature
        exp_preds = np.exp(preds)
        preds = exp_preds / np.sum(exp_preds)
        probas = np.random.multinomial(1, preds, 1)
        return np.argmax(probas)

    def _gen_generate_next(self, text, num_generated=16):
        """
        Generate and return a number of words based on a given seed.

        :param text: The seed text.
        :param num_generated: The number of words to generate.
        :return: The generated string, including the seed.
        """
        word_idxs = [self._gen_word2idx(word) for word in text.lower().split()]
        for i in range(num_generated):
            prediction = self.model.predict(x=np.array(word_idxs))
            idx = self._gen_sample(prediction[-1], temperature=0.7)
            word_idxs.append(idx)
        return ' '.join(self._gen_idx2word(idx) for idx in word_idxs)

    def _gen_on_epoch_end(self, epoch, _):
        """
        A method called after each epoch of training. Generates text with the model's sim-words as seeds.

        :param epoch: The epoch number.
        :param _: Unused variable.
        """
        print('\nGenerating text after epoch: %d' % epoch)

        for text in self.sim_words:
            sample = self._gen_generate_next(text)
            print('%s... -> %s' % (text, sample))
