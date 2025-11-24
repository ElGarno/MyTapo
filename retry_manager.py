"""
Centralized retry logic for MyTapo monitoring services.

This module provides decorators and utilities for retrying operations with exponential backoff,
special handling for authentication errors, and configurable retry policies.
"""

import asyncio
import functools
import logging
from typing import Callable, Any, Optional, Tuple, Type
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RetryPolicy:
    """Configuration for retry behavior"""
    max_retries: int = 3
    max_delay: int = 60
    initial_delay: float = 1.0
    exponential_base: int = 2
    raise_on_auth_error: bool = True


def is_authentication_error(error: Exception) -> bool:
    """
    Detect if an error is related to authentication/session timeout.

    Args:
        error: The exception to check

    Returns:
        True if the error indicates authentication/session issues
    """
    error_str = str(error)
    auth_indicators = ["403", "Forbidden", "SessionTimeout", "Response error", "Unauthorized"]
    return any(indicator in error_str for indicator in auth_indicators)


def retry_with_backoff(
    max_retries: int = 3,
    max_delay: int = 60,
    initial_delay: float = 1.0,
    exponential_base: int = 2,
    raise_on_auth_error: bool = True,
    exceptions: Tuple[Type[Exception], ...] = (Exception,)
):
    """
    Decorator for retrying sync functions with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        max_delay: Maximum delay between retries in seconds
        initial_delay: Initial delay before first retry
        exponential_base: Base for exponential backoff calculation
        raise_on_auth_error: If True, immediately raise authentication errors
        exceptions: Tuple of exception types to catch and retry

    Example:
        @retry_with_backoff(max_retries=5, max_delay=120)
        def fetch_data():
            # Your code here
            pass
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            retry_count = 0
            last_exception = None

            while retry_count <= max_retries:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    # Check for authentication errors
                    if raise_on_auth_error and is_authentication_error(e):
                        logger.error(f"Authentication error in {func.__name__}: {e}")
                        raise

                    retry_count += 1
                    if retry_count > max_retries:
                        logger.error(
                            f"Failed {func.__name__} after {max_retries} retries: {e}"
                        )
                        break

                    # Calculate delay with exponential backoff
                    delay = min(initial_delay * (exponential_base ** (retry_count - 1)), max_delay)
                    logger.warning(
                        f"Retry {retry_count}/{max_retries} for {func.__name__} "
                        f"after {delay}s delay. Error: {e}"
                    )

                    import time
                    time.sleep(delay)

            # If all retries exhausted, raise the last exception
            if last_exception:
                raise last_exception

        return wrapper
    return decorator


def async_retry_with_backoff(
    max_retries: int = 3,
    max_delay: int = 60,
    initial_delay: float = 1.0,
    exponential_base: int = 2,
    raise_on_auth_error: bool = True,
    exceptions: Tuple[Type[Exception], ...] = (Exception,)
):
    """
    Decorator for retrying async functions with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        max_delay: Maximum delay between retries in seconds
        initial_delay: Initial delay before first retry
        exponential_base: Base for exponential backoff calculation
        raise_on_auth_error: If True, immediately raise authentication errors
        exceptions: Tuple of exception types to catch and retry

    Example:
        @async_retry_with_backoff(max_retries=5, max_delay=120)
        async def fetch_data_async():
            # Your async code here
            pass
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            retry_count = 0
            last_exception = None

            while retry_count <= max_retries:
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    # Check for authentication errors
                    if raise_on_auth_error and is_authentication_error(e):
                        logger.error(f"Authentication error in {func.__name__}: {e}")
                        raise

                    retry_count += 1
                    if retry_count > max_retries:
                        logger.error(
                            f"Failed {func.__name__} after {max_retries} retries: {e}"
                        )
                        break

                    # Calculate delay with exponential backoff
                    delay = min(initial_delay * (exponential_base ** (retry_count - 1)), max_delay)
                    logger.warning(
                        f"Retry {retry_count}/{max_retries} for {func.__name__} "
                        f"after {delay}s delay. Error: {e}"
                    )

                    await asyncio.sleep(delay)

            # If all retries exhausted, raise the last exception
            if last_exception:
                raise last_exception

        return wrapper
    return decorator


async def retry_async_operation(
    operation: Callable,
    policy: Optional[RetryPolicy] = None,
    operation_name: str = "operation"
) -> Any:
    """
    Retry an async operation with the given policy.

    Args:
        operation: Async callable to retry
        policy: RetryPolicy configuration (uses default if None)
        operation_name: Name for logging purposes

    Returns:
        Result of the operation

    Raises:
        Last exception if all retries exhausted

    Example:
        result = await retry_async_operation(
            lambda: device.get_current_power(),
            policy=RetryPolicy(max_retries=5),
            operation_name="get_power"
        )
    """
    if policy is None:
        policy = RetryPolicy()

    retry_count = 0
    last_exception = None

    while retry_count <= policy.max_retries:
        try:
            return await operation()
        except Exception as e:
            last_exception = e

            # Check for authentication errors
            if policy.raise_on_auth_error and is_authentication_error(e):
                logger.error(f"Authentication error in {operation_name}: {e}")
                raise

            retry_count += 1
            if retry_count > policy.max_retries:
                logger.error(
                    f"Failed {operation_name} after {policy.max_retries} retries: {e}"
                )
                break

            # Calculate delay with exponential backoff
            delay = min(
                policy.initial_delay * (policy.exponential_base ** (retry_count - 1)),
                policy.max_delay
            )
            logger.warning(
                f"Retry {retry_count}/{policy.max_retries} for {operation_name} "
                f"after {delay}s delay. Error: {e}"
            )

            await asyncio.sleep(delay)

    # If all retries exhausted, raise the last exception
    if last_exception:
        raise last_exception
