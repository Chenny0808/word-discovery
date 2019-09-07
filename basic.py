#! -*- coding: utf-8 -*-

import struct
import os
import math
import logging
logging.basicConfig(level=logging.INFO, format=u'%(asctime)s - %(levelname)s - %(message)s')


class Progress:
    """显示进度，自己简单封装，比tqdm更可控一些
    iterator: 可迭代的对象；
    period: 显示进度的周期；
    steps: iterator可迭代的总步数，相当于len(iterator)
    """
    def __init__(self, iterator, period=1, steps=None, desc=None):
        self.iterator = iterator
        self.period = period
        if hasattr(iterator, '__len__'):
            self.steps = len(iterator)
        else:
            self.steps = steps
        self.desc = desc
        if self.steps:
            self._format_ = u'%s/%s passed' %('%s', self.steps)
        else:
            self._format_ = u'%s passed'
        if self.desc:
            self._format_ = self.desc + ' - ' + self._format_
        self.logger = logging.getLogger()
    def __iter__(self):
        for i, j in enumerate(self.iterator):
            if (i + 1) % self.period == 0:
                self.logger.info(self._format_ % (i+1))
            yield j


class KenlmNgrams:
    """加载Kenlm的ngram统计结果
    vocab_file: Kenlm统计出来的词(字)表；
    ngram_file: Kenlm统计出来的ngram表；
    order: 统计ngram时设置的n，必须跟ngram_file对应；
    min_count: 自行设置的截断频数。
    """
    def __init__(self, vocab_file, ngram_file, order, min_count):
        self.vocab_file = vocab_file
        self.ngram_file = ngram_file
        self.order = order
        self.min_count = min_count
        self.read_chars()
        self.read_ngrams()
    def read_chars(self):
        f = open(self.vocab_file)
        chars = f.read()
        f.close()
        chars = chars.split('\x00')
        self.chars = [i.decode('utf-8') for i in chars]
    def read_ngrams(self):
        """读取思路参考https://github.com/kpu/kenlm/issues/201
        """
        self.ngrams = [{} for _ in range(self.order)]
        self.total = 0
        size_per_item = self.order * 4 + 8
        f = open(self.ngram_file, 'rb')
        filedata = f.read()
        filesize = f.tell()
        f.close()
        for i in Progress(range(0, filesize, size_per_item), 100000, desc=u'loading ngrams'):
            s = filedata[i: i+size_per_item]
            n = self.unpack('l', s[-8:])
            if n >= self.min_count:
                self.total += n
                c = [self.unpack('i', s[j*4: (j+1)*4]) for j in range(self.order)]
                c = ''.join([self.chars[j] for j in c if j > 2])
                for j in range(len(c)):
                    self.ngrams[j][c[:j+1]] = self.ngrams[j].get(c[:j+1], 0) + n
    def unpack(self, t, s):
        return struct.unpack(t, s)[0]


def write_corpus(texts, filename):
    """将语料写到文件中，词与词(字与字)之间用空格隔开
    """
    with open(filename, 'w') as f:
        for s in Progress(texts, 10000, desc=u'exporting corpus'):
            s = ' '.join(s) + '\n'
            f.write(s.encode('utf-8'))


def count_ngrams(corpus_file, order, vocab_file, ngram_file):
    """通过os.system调用Kenlm的count_ngrams来统计频数
    """
    return os.system(
        './count_ngrams -o %s --write_vocab_list %s <%s >%s'
        % (order, vocab_file, corpus_file, ngram_file)
    )


def filter_ngrams(ngrams, total, min_pmi=1):
    """通过互信息过滤ngrams，只保留“结实”的ngram。
    """
    order = len(ngrams)
    if hasattr(min_pmi, '__iter__'):
        min_pmi = list(min_pmi)
    else:
        min_pmi = [min_pmi] * order
    output_ngrams = set()
    total = float(total)
    for i in range(order-1, 0, -1):
        for w, v in ngrams[i].items():
            pmi = min([
                total * v / (ngrams[j].get(w[:j+1], total) * ngrams[i-j-1].get(w[j+1:], total))
                for j in range(i)
            ])
            if math.log(pmi) >= min_pmi[i]:
                output_ngrams.add(w)
    return output_ngrams


class SimpleTrie:
    """通过Trie树结构，来搜索ngrams组成的连续片段
    """
    def __init__(self):
        self.dic = {}
        self.end = True
    def add_word(self, word):
        _ = self.dic
        for c in word:
            if c not in _:
                _[c] = {}
            _ = _[c]
        _[self.end] = word
    def tokenize(self, sent): # 通过最长联接的方式来对句子进行分词
        result = []
        start, end = 0, 1
        for i, c1 in enumerate(sent):
            _ = self.dic
            if i == end:
                result.append(sent[start: end])
                start, end = i, i+1
            for j, c2 in enumerate(sent[i:]):
                if c2 in _:
                    _ = _[c2]
                    if self.end in _:
                        if i + j + 1 > end:
                            end = i + j + 1
                else:
                    break
        result.append(sent[start: end])
        return result


def filter_vocab(candidates, ngrams, order):
    """通过与ngrams对比，排除可能出来的不牢固的词汇
    """
    result = {}
    for i, j in candidates.items():
        if len(i) < 3:
            result[i] = j
        elif len(i) <= order and i in ngrams:
            result[i] = j
        elif len(i) > order:
            flag = True
            for k in range(len(i) + 1 - order):
                if i[k: k+order] not in ngrams:
                    flag = False
            if flag:
                result[i] = j
    return result