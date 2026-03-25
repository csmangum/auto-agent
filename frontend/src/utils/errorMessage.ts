/**
 * Normalize unknown thrown values to a user-visible string (e.g. for toasts).
 * Handles Error, non-empty strings, and plain objects with a string `message`.
 */

export function getErrorMessage(error: unknown, fallback = 'Something went wrong'): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  if (typeof error === 'string' && error.trim()) {
    return error.trim();
  }
  if (
    error &&
    typeof error === 'object' &&
    'message' in error &&
    typeof (error as { message: unknown }).message === 'string' &&
    (error as { message: string }).message.trim()
  ) {
    return (error as { message: string }).message.trim();
  }
  return fallback;
}
