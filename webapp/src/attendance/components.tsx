import type { RsvpStatus } from '../api/attendance';
import { initials } from '../ui/initials';

type Segment = {
  value: RsvpStatus;
  glyph: string;
  label: string;
};

const SEGMENTS: readonly Segment[] = [
  { value: 'going', glyph: '✅', label: 'участвует' },
  { value: 'not_going', glyph: '❌', label: 'не участвует' },
  { value: null, glyph: '⚪', label: 'не ответил' },
];

/**
 * Сегментированный переключатель RSVP одного участника: три состояния
 * (участвует / не участвует / не ответил) в один тап, без цикличного тоггла
 * (docs/_draft п. 4). `pending` — идёт запрос, контрол заблокирован.
 */
export function StatusSegments({
  value,
  pending,
  onPick,
}: {
  value: RsvpStatus;
  pending: boolean;
  onPick: (next: RsvpStatus) => void;
}) {
  return (
    <div className="at-seg" role="group">
      {SEGMENTS.map((segment) => {
        const active = segment.value === value;
        return (
          <button
            key={segment.label}
            type="button"
            className={`at-seg__btn${active ? ' at-seg__btn--active' : ''}`}
            aria-pressed={active}
            aria-label={segment.label}
            disabled={pending}
            onClick={() => {
              if (!active) onPick(segment.value);
            }}
          >
            <span aria-hidden="true">{segment.glyph}</span>
          </button>
        );
      })}
    </div>
  );
}

export function ParticipantRow({
  name,
  value,
  pending,
  error,
  onPick,
}: {
  name: string;
  value: RsvpStatus;
  pending: boolean;
  error: boolean;
  onPick: (next: RsvpStatus) => void;
}) {
  return (
    <div className={`at-row${error ? ' at-row--error' : ''}`}>
      <span className="at-avatar" aria-hidden="true">
        {initials(name)}
      </span>
      <span className="at-row__name">{name}</span>
      <StatusSegments value={value} pending={pending} onPick={onPick} />
    </div>
  );
}
