import dogpile

from ...pin import Pin


class _ProxyMutex(object):
    def __init__(self, mutex):
        self._mutex = mutex

    def acquire(self, wait=True):
        pin = Pin.get_from(dogpile.cache)
        if not pin or not pin.enabled():
            return self._mutex.acquire(wait=wait)

        with pin.tracer.trace('dogpile.cache', resource='acquire_lock', span_type='cache'):
            return self._mutex.acquire(wait=wait)

    def release(self):
        pin = Pin.get_from(dogpile.cache)
        if not pin or not pin.enabled():
            return self._mutex.release()

        with pin.tracer.trace('dogpile.cache', resource='release_lock', span_type='cache'):
            return self._mutex.release()


def _wrap_lock_ctor(func, instance, args, kwargs):
    """
    This seems rather odd. But to track hits, we need to patch the wrapped function that
    dogpile passes to the region and locks. In addition, this gives us the opportunity
    to replace the mutex instance with a proxy so we can also track lock acquisitions
    and releases in separate spans.
    """
    new_args = [_ProxyMutex(args[0])]
    new_args.extend(args[1:])
    func(*new_args, **kwargs)
    ori_backend_fetcher = instance.value_and_created_fn

    def wrapped_backend_fetcher():
        pin = Pin.get_from(dogpile.cache)
        if not pin or not pin.enabled():
            return ori_backend_fetcher()

        hit = False
        expired = True
        try:
            value, createdtime = ori_backend_fetcher()
            hit = value == dogpile.cache.api.NoValue
            # dogpile sometimes returns None, but only checks for truthiness. Coalesce
            # to minimize APM users' confusion.
            expired = instance._is_expired(createdtime) or False
            return value, createdtime
        finally:
            pin.tracer.current_span().set_tag('hit', hit)
            pin.tracer.current_span().set_tag('expired', expired)
    instance.value_and_created_fn = wrapped_backend_fetcher
