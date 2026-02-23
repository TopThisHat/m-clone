import { writable } from 'svelte/store';
import type { User } from '$lib/api/auth';

export const currentUser = writable<User | null>(null);
