export async function queryRead<T>(
  signal: AbortSignal,
  createAbortController: () => AbortController,
  releaseAbortController: (controller: AbortController) => void,
  read: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  const controller = createAbortController();
  const abort = () => controller.abort();
  if (signal.aborted) abort();
  else signal.addEventListener("abort", abort, { once: true });
  try {
    return await read(controller.signal);
  } finally {
    signal.removeEventListener("abort", abort);
    releaseAbortController(controller);
  }
}
