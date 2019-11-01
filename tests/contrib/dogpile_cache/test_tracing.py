import dogpile
import pytest
import wrapt

from ddtrace import Pin
from ddtrace.contrib.dogpile_cache.patch import patch, unpatch
from ddtrace.contrib.dogpile_cache.region import _wrap_get_create, _wrap_get_create_multi

from tests.test_tracer import get_dummy_tracer


@pytest.fixture
def tracer():
    return get_dummy_tracer()


@pytest.fixture
def region(tracer):
    patch()
    # Setup a simple dogpile cache region for testing.
    # The backend is trivial so we can use memory to simplify test setup.
    test_region = dogpile.cache.make_region(name='TestRegion')
    test_region.configure('dogpile.cache.memory')
    Pin.override(dogpile.cache, tracer=tracer)
    return test_region


@pytest.fixture(autouse=True)
def cleanup():
    yield
    unpatch()


@pytest.fixture
def single_cache(region):
    @region.cache_on_arguments()
    def fn(x):
        return x * 2
    return fn


@pytest.fixture
def multi_cache(region):
    @region.cache_multi_on_arguments()
    def fn(*x):
        print(x)
        return [i * 2 for i in x]

    return fn


def test_doesnt_trace_with_no_pin(tracer, single_cache, multi_cache):
    # No pin is set
    unpatch()

    assert single_cache(1) == 2
    assert tracer.writer.pop_traces() == []

    assert multi_cache(2, 3) == [4, 6]
    assert tracer.writer.pop_traces() == []


def test_doesnt_trace_with_disabled_pin(tracer, single_cache, multi_cache):
    tracer.enabled = False

    assert single_cache(1) == 2
    assert tracer.writer.pop_traces() == []

    assert multi_cache(2, 3) == [4, 6]
    assert tracer.writer.pop_traces() == []


def test_traces(tracer, single_cache, multi_cache):
    assert single_cache(1) == 2
    traces = tracer.writer.pop_traces()
    assert len(traces) == 1
    spans = traces[0]
    assert len(spans) == 3
    span = spans[0]
    assert span.name == 'dogpile.cache'
    assert span.resource == 'get_or_create'
    assert span.meta['key'] == 'tests.contrib.dogpile_cache.test_tracing:fn|1'
    assert span.meta['hit'] == 'False'
    assert span.meta['expired'] == 'True'
    assert span.meta['backend'] == 'MemoryBackend'
    assert span.meta['region'] == 'TestRegion'
    span = spans[1]
    assert span.name == 'dogpile.cache'
    assert span.resource == 'acquire_lock'
    # Normally users will probably also enable tracing for their specific cache system,
    # in which case a span in the middle would be here showing the actual lookup. But
    # that's not the job of this tracing. Just FYI.
    span = spans[2]
    assert span.name == 'dogpile.cache'
    assert span.resource == 'release_lock'

    assert multi_cache(2, 3) == [4, 6]
    traces = tracer.writer.pop_traces()
    assert len(traces) == 1
    spans = traces[0]
    print([(s.name, s.resource, s.meta) for s in spans])
    assert len(spans) == 5
    span = spans[0]
    assert span.meta['keys'] == (
        "['tests.contrib.dogpile_cache.test_tracing:fn|2', "
        + "'tests.contrib.dogpile_cache.test_tracing:fn|3']"
    )
    assert span.meta['hit'] == 'False'
    assert span.meta['expired'] == 'True'
    assert span.meta['backend'] == 'MemoryBackend'
    assert span.meta['region'] == 'TestRegion'
    span = spans[1]
    assert span.name == 'dogpile.cache'
    assert span.resource == 'acquire_lock'
    span = spans[2]
    assert span.name == 'dogpile.cache'
    assert span.resource == 'acquire_lock'
    span = spans[3]
    assert span.name == 'dogpile.cache'
    assert span.resource == 'release_lock'
    span = spans[4]
    assert span.name == 'dogpile.cache'
    assert span.resource == 'release_lock'
