import { toast } from "sonner";
import { ApiError } from "./api";

export function notifyError(err: unknown, fallback = "Something went wrong.") {
  if (err instanceof ApiError) {
    toast.error(err.message, {
      description: err.requestId ? `Request ID: ${err.requestId}` : undefined,
      duration: 8000,
    });
  } else {
    toast.error(fallback);
  }
}

export const notifyOk = (message: string, description?: string) => toast.success(message, { description });
