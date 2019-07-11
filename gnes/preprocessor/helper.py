#  Tencent is pleased to support the open source community by making GNES available.
#
#  Copyright (C) 2019 THL A29 Limited, a Tencent company. All rights reserved.
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

# pylint: disable=low-comment-ratio

import io
import subprocess as sp

import cv2
import numpy as np
from PIL import Image


def get_video_frames(buffer_data, image_format="cv2", **kwargs):
    ffmpeg_cmd = ['ffmpeg', '-i', '-', '-f', 'image2pipe']

    # example k,v pair:
    #    (-s, 420*360)
    #    (-vsync, vfr)
    #    (-vf, select=eq(pict_type\,I))
    for k, v in kwargs.items():
        ffmpeg_cmd.append('-' + k)
        ffmpeg_cmd.append(v)

    # (-c:v, png) output bytes in png format
    # (-an, -sn) disable audio processing
    # (-) output to stdout pipeline
    ffmpeg_cmd += ['-c:v', 'png', '-an', '-sn', '-']

    with sp.Popen(ffmpeg_cmd, stdin=sp.PIPE, stdout=sp.PIPE, bufsize=-1, shell=False) as pipe:
        stream, _ = pipe.communicate(buffer_data)

        # raw bytes for multiple PNGs.
        # split by PNG EOF b'\x89PNG'
        stream = stream.split(b'\x89PNG')

        if len(stream) <= 1:
            return []

        # reformulate the full pngs for feature processings.
        if image_format == 'pil':
            frames = [Image.open(io.BytesIO(b'\x89PNG' + _)) for _ in stream[1:]]
        elif image_format == 'cv2':
            frames = [
                cv2.imdecode(np.frombuffer(b'\x89PNG' + _, np.uint8), 1)
                for _ in stream[1:]
            ]
        else:
            raise NotImplementedError

    return frames


def block_descriptor(image, descriptor_fn, num_blocks):
    h, w, _ = image.shape    # find shape of image and channel
    block_h = int(np.ceil(h / num_blocks))
    block_w = int(np.ceil(w / num_blocks))

    descriptors = []
    for i in range(0, h, block_h):
        for j in range(0, w, block_w):
            block = image[i:i + block_h, j:j + block_w]
            descriptors.extend(descriptor_fn(block))

    return np.array(descriptors)


def pyramid_descriptor(image, descriptor_fn, max_level):
    descriptors = []
    for level in range(max_level + 1):
        num_blocks = 2**level
        descriptors.extend(block_descriptor(image, descriptor_fn, num_blocks))

    return np.array(descriptors)


def rgb_histogram(image):
    _, _, c = image.shape
    hist = [
        cv2.calcHist([image], [i], None, [256], [0, 256]) for i in range(c)
    ]
    # normalize hist
    hist = np.array([h / np.sum(h) for h in hist]).flatten()
    return hist


def hsv_histogram(image):
    _, _, c = image.shape
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)

    # sizes = [180, 256, 256]
    # ranges = [(0, 180), (0, 256), (0, 256)]

    # hist = [
    #     cv2.calcHist([hsv], [i], None, [sizes[i]], ranges[i]) for i in range(c)
    # ]

    hist = [
        cv2.calcHist([hsv], [i], None, [256], [0, 256]) for i in range(c)
    ]
    # normalize hist
    hist = np.array([h / np.sum(h) for h in hist]).flatten()
    return hist


def compute_descriptor(image, method="rgb_histogram", **kwargs):
    funcs = {
        'rgb_histogram': rgb_histogram,
        'hsv_histogram': hsv_histogram,
        'block_rgb_histogram': lambda image: block_descriptor(image, rgb_histogram, kwargs.get("num_blocks", 3)),
        'block_hsv_histogram': lambda image: block_descriptor(image, hsv_histogram, kwargs.get("num_blocks", 3)),
        'pyramid_rgb_histogram': lambda image: pyramid_descriptor(image, rgb_histogram, kwargs.get("max_level", 2)),
        'pyramid_hsv_histogram': lambda image: pyramid_descriptor(image, hsv_histogram, kwargs.get("max_level", 2)),
    }
    return funcs[method](image)


def compare_descriptor(descriptor1, descriptor2, metric="chisqr"):
    dist_metric = {
        "correlation": cv2.HISTCMP_CORREL,
        "chisqr": cv2.HISTCMP_CHISQR,
        "chisqr_alt": cv2.HISTCMP_CHISQR_ALT,
        "intersection": cv2.HISTCMP_INTERSECT,
        "bhattacharya": cv2.HISTCMP_BHATTACHARYYA,
        "hellinguer": cv2.HISTCMP_HELLINGER,
        "kl_div": cv2.HISTCMP_KL_DIV
    }

    return cv2.compareHist(descriptor1, descriptor2, dist_metric[metric])

def pil_to_array(pil_image: Image):
    """
    Load a PIL image and return it as a numpy array.  For grayscale
    images, the return array is MxN.  For RGB images, the return value
    is MxNx3.  For RGBA images the return value is MxNx4
    """

    def toarray(im, dtype=np.uint8):
        """Return a 1D array of dtype."""
        # Pillow wants us to use "tobytes"
        if hasattr(im, 'tobytes'):
            x_str = im.tobytes('raw', im.mode)
        else:
            x_str = im.tostring('raw', im.mode)
        x = np.fromstring(x_str, dtype)
        return x

    if pil_image.mode in ('RGBA', 'RGBX'):
        im = pil_image    # no need to convert images
    elif pil_image.mode == 'L':
        im = pil_image    # no need to luminance images
        # return MxN luminance array
        x = toarray(im)
        x.shape = im.size[1], im.size[0]
        return x
    elif pil_image.mode == 'RGB':
        # return MxNx3 RGB array
        im = pil_image    # no need to RGB images
        x = toarray(im)
        x.shape = im.size[1], im.size[0], 3
        return x
    elif pil_image.mode.startswith('I;16'):
        # return MxN luminance array of uint16
        im = pil_image
        if im.mode.endswith('B'):
            x = toarray(im, '>u2')
        else:
            x = toarray(im, '<u2')
        x.shape = im.size[1], im.size[0]
        return x.astype('=u2')
    else:    # try to convert to an rgba image
        try:
            im = pil_image.convert('RGBA')
        except ValueError:
            raise RuntimeError('Unknown image mode')

    # return MxNx4 RGBA array
    x = toarray(im)
    x.shape = im.size[1], im.size[0], 4
    return x