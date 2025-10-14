from typing import Any, Callable, NoReturn, TypeVar

T = TypeVar("T")

class _MarkDecorator:
    def parametrize(self, *args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]: ...

mark: _MarkDecorator

def fixture(func: Callable[..., T] | None = ..., *args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]: ...

def fail(message: str, *args: Any, **kwargs: Any) -> NoReturn: ...
