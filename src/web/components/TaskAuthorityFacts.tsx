import type {ReactNode} from 'react';
/** Owners supply four separate projections; no plan implies execution. */
export function TaskAuthorityFacts({sourcePlan, operationalPlan, envelope, execution}: {
  sourcePlan: ReactNode; operationalPlan: ReactNode; envelope: ReactNode; execution: ReactNode;
}) {
  return <section aria-label="Task and Objective authorities"><h2>Source WFM plan</h2>{sourcePlan}
    <h2>Accepted operational Task plan</h2>{operationalPlan}
    <h2>Objective envelope</h2>{envelope}
    <h2>Actual execution</h2>{execution}
    <p>Starting an Objective does not start its member Tasks. Execution evidence is recorded by the owning Task command.</p>
  </section>;
}
