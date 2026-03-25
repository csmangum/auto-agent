/**
 * Normalize unknown thrown values to a user-visible string (e.g. for toasts).
 */

export function getErrorMessage(error: unknown, fallback = 'Something went wrong'): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return fallback;
}
