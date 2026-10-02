import type {ReactNode} from 'react';
export function BoundedCollection({rows, next, onNext, caption, nextFocusToken,returnScrollToken}: {
  rows: readonly Readonly<{id: string; cells: readonly ReactNode[]}>[]; next: boolean; onNext: () => void; caption: string; nextFocusToken?:string;returnScrollToken?:string;
}) {
  if (rows.length > 200 || rows.some(row=>typeof row.id!=='string'||row.id.length===0)
    || new Set(rows.map(row => row.id)).size !== rows.length) throw new Error('Collection violates its bounded unique page contract');
  return <section><div className="table-owner" data-scroll-owner="both" data-return-scroll={returnScrollToken}><table><caption>{caption}</caption><tbody>
    {rows.map(row => <tr key={row.id}>{row.cells.map((cell, index) => <td key={index}>{cell}</td>)}</tr>)}
  </tbody></table></div>{next && <button type="button" data-focus-token={nextFocusToken} onClick={onNext}>Next page</button>}{next && <p role="status">Additional results are available.</p>}</section>;
}
