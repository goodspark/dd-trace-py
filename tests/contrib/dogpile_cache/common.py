from dogpile.cache import make_region


# Setup a simple dogpile cache region for testing.
# The backend is trivial so we can use memory to simplify test setup.
test_region = make_region(name='TestRegion')
# This lets us 'flush' the region between tests.
cache_dict = {}
test_region.configure('dogpile.cache.memory', arguments={'cache_dict': cache_dict})
