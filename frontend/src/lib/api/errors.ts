/**
 * Converts an HTTP response into a user-friendly error message.
 * Never leaks raw stack traces or internal keys.
 */
export async function friendlyError(res: Response, fallback = 'Something went wrong — please try again.'): Promise<string> {
	switch (res.status) {
		case 400: {
			const body = await res.json().catch(() => ({}));
			const detail = body?.detail;
			if (typeof detail === 'string' && detail.length < 200) return detail;
			return 'Invalid request — please check your input.';
		}
		case 401:
			return 'You need to be logged in to do this.';
		case 403:
			return "You don't have permission to do this.";
		case 404:
			return 'Not found.';
		case 409:
			return 'That already exists — try a different name or slug.';
		case 422:
			return 'Invalid input — please check your fields.';
		case 503: {
			// Server sends a user-facing detail for 503 — use it, or give a generic message
			const body = await res.json().catch(() => ({}));
			const detail = body?.detail;
			if (typeof detail === 'string' && detail.length < 300) return detail;
			return 'This feature is currently unavailable.';
		}
		default:
			return fallback;
	}
}

/** Throws with a friendly message if response is not ok. */
export async function assertOk(res: Response, fallback?: string): Promise<void> {
	if (res.ok) return;
	const msg = await friendlyError(res, fallback);
	throw new Error(msg || fallback || 'Something went wrong.');
}
