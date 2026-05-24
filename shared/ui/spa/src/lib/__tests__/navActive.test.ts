import { describe, expect, it, vi } from 'vitest';

vi.mock('$app/paths', () => ({ base: '/spa' }));

import { isNavItemActive, normalizePathname } from '../navActive';

describe('normalizePathname', () => {
  it('strips base prefix when present', () => {
    expect(normalizePathname('/spa/panels/hub-inbox')).toBe('/panels/hub-inbox');
  });

  it('leaves pathname unchanged when already relative to base', () => {
    expect(normalizePathname('/panels/hub-inbox')).toBe('/panels/hub-inbox');
  });
});

describe('isNavItemActive', () => {
  it('highlights Hub inbox via route id', () => {
    expect(isNavItemActive('/spa/panels/hub-inbox', '/panels/hub-inbox', '/panels/hub-inbox')).toBe(
      true,
    );
    expect(isNavItemActive('/spa/panels/hub-inbox', '/panels/role-chat', '/panels/hub-inbox')).toBe(
      false,
    );
  });

  it('highlights via pathname when route id absent', () => {
    expect(isNavItemActive('/panels/role-chat', '/panels/role-chat', null)).toBe(true);
    expect(isNavItemActive('/spa/panels/role-chat', '/panels/role-chat', null)).toBe(true);
  });

  it('highlights Projects on list and detail routes', () => {
    expect(isNavItemActive('/projects', '/projects', '/projects')).toBe(true);
    expect(isNavItemActive('/projects/9', '/projects', '/projects/[project_id]')).toBe(true);
    expect(isNavItemActive('/panels/hub-inbox', '/projects', '/panels/hub-inbox')).toBe(false);
  });

  it('highlights Dashboard only on root', () => {
    expect(isNavItemActive('/', '/', '/')).toBe(true);
    expect(isNavItemActive('/spa', '/', '/')).toBe(true);
    expect(isNavItemActive('/projects', '/', '/projects')).toBe(false);
  });
});
