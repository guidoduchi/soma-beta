import {OwnerProjection} from '../components/OwnerProjection';

/** Exact LLD-05 GetObjectiveTimezone response; owner resolves the IANA identifier. */
type ObjectiveTimezoneV1 = Readonly<{iana_timezone: string; source: 'DEFAULT' | 'PERSISTED'; revision: number | null}>;
export function ObjectiveSettings() {
  return <section aria-label="Objective scheduling settings"><h2>Objective scheduling timezone</h2>
    <OwnerProjection<ObjectiveTimezoneV1> path="/api/v1/settings/objective-timezone" render={value => {
      if (Object.keys(value).length !== 3 || typeof value.iana_timezone !== 'string' || !value.iana_timezone
          || new TextEncoder().encode(value.iana_timezone).length > 255
          || (value.source === 'DEFAULT' ? value.revision !== null
            : value.source !== 'PERSISTED' || !Number.isSafeInteger(value.revision) || (value.revision ?? 0) < 1)) {
        throw new Error('Invalid owner Objective timezone');
      }
      return <><p>Scheduling timezone: {value.iana_timezone}. Source: {value.source}; revision: {value.revision ?? 'Default'}.</p>
        <p>This timezone governs Task and Objective scheduling interpretation and calendar presentation. Accepted UTC plans and execution instants remain owner evidence.</p>
        <p>Ordinary application and SLA chronology follow their own America/Guayaquil contracts. Preserving schedule wall-clock labels under another timezone requires a separately reviewed Task reschedule or correction.</p></>;
    }}/></section>;
}
