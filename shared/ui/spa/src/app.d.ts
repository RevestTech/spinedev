// SvelteKit ambient type declarations (V3 Wave 3 part 2, Squad SPA1).
// See https://kit.svelte.dev/docs/types#app

import type { SpineUser } from '$lib/api/types';

declare global {
  namespace App {
    interface Error {
      code?: string;
      message: string;
    }
    interface Locals {
      user?: SpineUser;
    }
    interface PageData {
      user?: SpineUser;
    }
    // interface PageState {}
    // interface Platform {}
  }
}

export {};
