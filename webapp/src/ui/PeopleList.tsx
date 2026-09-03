import type { EventViewPerson } from '../api/events';
import { initials } from './initials';
import './people-list.css';

/**
 * Список людей: кружок-инициалы + имя. Используется в карточке «Кто идёт»
 * на экране мероприятия — это «дом» для кнопки «полный список» из анонса,
 * который при переполнении лимита длины сворачивает никнеймы в числа.
 */
export function PeopleList({ people }: { people: EventViewPerson[] }) {
  return (
    <ul className="people-list">
      {people.map((person) => (
        <li key={person.user_id} className="people-list__row">
          <span className="people-list__avatar" aria-hidden="true">
            {initials(person.name)}
          </span>
          <span className="people-list__name">{person.name}</span>
        </li>
      ))}
    </ul>
  );
}
