import { describe, expect, it } from 'vitest';

import { initials } from './initials';

describe('initials', () => {
  it('берёт первые буквы имени и фамилии', () => {
    expect(initials('Миша Родин')).toBe('МР');
  });

  it('из одного слова — одна буква', () => {
    expect(initials('Аня')).toBe('А');
  });

  it('не больше двух букв', () => {
    expect(initials('Анна Мария Ковалёва')).toBe('АМ');
  });

  it('схлопывает лишние пробелы и пустую строку', () => {
    expect(initials('  Пётр   Ильич  ')).toBe('ПИ');
    expect(initials('')).toBe('');
  });
});
