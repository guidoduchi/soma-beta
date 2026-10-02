/** LLD-09 ChronologyV1, using the accepted whole-second owner refinement.
 * Source/provider checkpoint milliseconds belong to a different owner DTO.
 */
export type ChronologyV1 = Readonly<{known: boolean; utc_epoch_seconds: number | null;
  source_kind: 'RECEIVED_TIME' | 'SENT_TIME' | 'OTHER_PROVIDER_TIME' | 'UNKNOWN'}>;

export function validChronology(value: ChronologyV1): boolean {
  if (!value || typeof value.known !== 'boolean' || Object.keys(value).length !== 3
      || !Object.hasOwn(value, 'utc_epoch_seconds') || !Object.hasOwn(value, 'source_kind')) return false;
  return value.known ? Number.isSafeInteger(value.utc_epoch_seconds) && (value.utc_epoch_seconds ?? -1) >= 0
    && ['RECEIVED_TIME', 'SENT_TIME', 'OTHER_PROVIDER_TIME'].includes(value.source_kind)
    : value.utc_epoch_seconds === null && value.source_kind === 'UNKNOWN';
}
