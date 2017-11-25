import lz4.block
import sys
from multiprocessing.pool import ThreadPool
import os
import pytest

test_data=[
    (b''),
    (os.urandom(128 * 1024)),
    (b'0' * 128 * 1024),
]
@pytest.fixture(
    params=test_data,
    ids=[
        'data' + str(i) for i in range(len(test_data))
    ]
)
def data(request):
    return request.param

@pytest.fixture(
    params=[
        (
            {
                'store_size': True
            }
        ),
        (
            {
                'store_size': False
            }
        ),
    ]
)
def store_size(request):
    return request.param

@pytest.fixture(
    params=[
        (
            {
                'return_bytearray': True
            }
        ),
        (
            {
                'return_bytearray': False
            }
        ),
    ]
)
def return_bytearray(request):
    return request.param

@pytest.fixture
def c_return_bytearray(return_bytearray):
    return return_bytearray

@pytest.fixture
def d_return_bytearray(return_bytearray):
    return return_bytearray

@pytest.fixture(
    params=[
        ('fast', None)
    ] + [
        ('fast', {'acceleration': s}) for s in range(10)
    ] + [
        ('high_compression', None)
    ] + [
        ('high_compression', {'compression': s}) for s in range(17)
    ] + [
        (None, None)
    ]
)
def mode(request):
    return request.param

def get_stored_size(buff):
    if sys.version_info > (3, 2):
        return int.from_bytes(buff[:4], 'little')
    else:
        import struct
        return struct.unpack('<I', bytes(buff[:4]))[0]


# Test single threaded usage with all valid variations of input
def test_1(data, mode, store_size, c_return_bytearray, d_return_bytearray):
    kwargs = {}

    if mode[0] != None:
        kwargs['mode'] = mode[0]
    if mode[1] != None:
        kwargs.update(mode[1])

    kwargs.update(store_size)
    kwargs.update(c_return_bytearray)

    c = []
    c += [lz4.block.compress(data, **kwargs)]
    c += [lz4.block.compress(bytearray(data), **kwargs)]
    assert (c.count(c[0]) == len(c)) # Check all list members equal
    for cc in c:
        if store_size['store_size']:
            assert(get_stored_size(cc) == len(data))
            d = lz4.block.decompress(cc, **d_return_bytearray)
        else:
            d = lz4.block.decompress(cc, uncompressed_size=len(data),
                                      **d_return_bytearray)
        assert(d == data)


# Test multi threaded usage with all valid variations of input
def test_threads2(data, mode, store_size):
    kwargs = {}
    if mode[0] != None:
        kwargs['mode'] = mode[0]
    if mode[1] != None:
        kwargs.update(mode[1])

    kwargs.update(store_size)

    def roundtrip(x):
        c = lz4.block.compress(x, **kwargs)
        if store_size['store_size']:
            assert(get_stored_size(c) == len(data))
            d = lz4.block.decompress(c)
        else:
            d = lz4.block.decompress(c, uncompressed_size=len(x))
        return d

    data_in = [data for i in range(32)]

    pool = ThreadPool(8)
    data_out = pool.map(roundtrip, data_in)
    pool.close()
    assert data_in == data_out


def test_decompress_ui32_overflow():
    data = lz4.block.compress(b'A' * 64)
    with pytest.raises(OverflowError):
        lz4.block.decompress(data[4:], uncompressed_size=((1<<32) + 64))


def test_decompress_without_leak():
    # Verify that hand-crafted packet does not leak uninitialized(?) memory.
    data = lz4.block.compress(b'A' * 64)
    message=r'^Decompressor wrote 64 bytes, but 79 bytes expected from header$'
    with pytest.raises(ValueError, message=message):
        lz4.block.decompress(b'\x4f' + data[1:])
    with pytest.raises(ValueError, message=message):
        lz4.block.decompress(data[4:], uncompressed_size=79)


def test_decompress_truncated():
    input_data = b"2099023098234882923049823094823094898239230982349081231290381209380981203981209381238901283098908123109238098123" * 24
    compressed = lz4.block.compress(input_data)
    # for i in range(len(compressed)):
    #     try:
    #         lz4.block.decompress(compressed[:i])
    #     except:
    #         print(i, sys.exc_info()[0], sys.exc_info()[1])
    with pytest.raises(ValueError, message='Input source data size too small'):
        lz4.block.decompress(compressed[:0])
        lz4.block.decompress(compressed[:1])
    with pytest.raises(ValueError, message=r'^Corrupt input at byte'):
        lz4.block.decompress(compressed[:24])
        lz4.block.decompress(compressed[:25])
        lz4.block.decompress(compressed[:-2])
    with pytest.raises(ValueError, message=r'Decompressor wrote \d+ bytes, but \d+ bytes expected from header)'):
        lz4.block.decompress(compressed[:27])
        lz4.block.decompress(compressed[:67])
        lz4.block.decompress(compressed[:85])


def test_decompress_with_trailer():
    data = b'A' * 64
    comp = lz4.block.compress(data)
    message=r'^Corrupt input at byte'
    with pytest.raises(ValueError, message=message):
        lz4.block.decompress(comp + b'A')
    with pytest.raises(ValueError, message=message):
        lz4.block.decompress(comp + comp)
    with pytest.raises(ValueError, message=message):
        lz4.block.decompress(comp + comp[4:])


def test_unicode():
    if sys.version_info < (3,):
        return  # skip
    DATA = b'x'
    with pytest.raises(TypeError):
        lz4.block.compress (DATA.decode('latin1'))
        lz4.block.decompress(lz4.block.compress(DATA).decode('latin1'))


def test_return_bytearray():
    if sys.version_info < (3,):
        return  # skip
    data = os.urandom(128 * 1024)  # Read 128kb
    compressed = lz4.block.compress(data)
    b = lz4.block.compress(data, return_bytearray=True)
    assert(type(b) == bytearray)
    assert(bytes(b) == compressed)
    b = lz4.block.decompress(compressed, return_bytearray=True)
    assert(type(b) == bytearray)
    assert(bytes(b) == data)

def test_memoryview():
    if sys.version_info < (2, 7):
        return  # skip
    data = os.urandom(128 * 1024)  # Read 128kb
    compressed = lz4.block.compress(data)
    assert(lz4.block.compress(memoryview(data)) == compressed)
    assert(lz4.block.decompress(memoryview(compressed)) == data)
