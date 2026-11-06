/** Loading skeletons at the sizes of the real cards (no shimmer under reduced motion: home.css). */

export function TeamCardSkeleton() {
  return (
    <div className="hm-glass hm-team" aria-hidden="true" data-testid="team-skeleton" style={{ minHeight: 280 }}>
      <div className="hm-team-top">
        <span className="hm-skel" style={{ width: 86, height: 22 }} />
        <span className="hm-skel" style={{ width: 104, height: 30 }} />
      </div>
      <div className="hm-team-names">
        <span className="hm-skel" style={{ width: "70%", height: 22 }} />
        <span className="hm-skel" style={{ width: "45%", height: 14 }} />
      </div>
      <div className="hm-stats">
        {[0, 1, 2].map((i) => (
          <div className="hm-stat" key={i}>
            <span className="hm-skel" style={{ width: 40, height: 10, display: "block" }} />
            <span className="hm-skel" style={{ width: 56, height: 22, display: "block", marginTop: 8 }} />
          </div>
        ))}
      </div>
      <span className="hm-skel" style={{ width: "60%", height: 14 }} />
      <div className="hm-team-cta">
        <span className="hm-skel" style={{ display: "block", height: 44, borderRadius: 12 }} />
      </div>
    </div>
  );
}

export function TeamsSkeleton() {
  return (
    <section className="hm-sec" aria-busy="true" aria-label="Loading your teams">
      <div className="hm-sec-head">
        <span className="hm-skel" style={{ width: 96, height: 12 }} />
        <span className="hm-skel" style={{ width: 80, height: 12 }} />
      </div>
      <div className="hm-teams">
        <TeamCardSkeleton />
        <TeamCardSkeleton />
        <TeamCardSkeleton />
      </div>
    </section>
  );
}

export function LowerSkeleton() {
  return (
    <div className="hm-lower" aria-busy="true" aria-label="Loading">
      <div className="hm-glass hm-gen" aria-hidden="true">
        <div className="hm-gen-head">
          <span className="hm-skel" style={{ width: 48, height: 48, borderRadius: 12 }} />
          <div>
            <span className="hm-skel" style={{ width: "40%", height: 20 }} />
            <span className="hm-skel" style={{ width: "70%", height: 14 }} />
          </div>
        </div>
        <div className="hm-chips">
          {[0, 1, 2, 3].map((i) => (
            <span key={i} className="hm-skel" style={{ height: 44, borderRadius: 999 }} />
          ))}
        </div>
        <span className="hm-skel" style={{ width: 200, height: 44, borderRadius: 12 }} />
      </div>
      <div className="hm-glass hm-recent" aria-hidden="true">
        <div className="hm-recent-head">
          <span className="hm-skel" style={{ width: 110, height: 12 }} />
        </div>
        {[0, 1, 2, 3, 4].map((i) => (
          <div className="hm-row" key={i}>
            <span className="hm-skel" style={{ width: 32, height: 32 }} />
            <div className="hm-row-body">
              <span className="hm-skel" style={{ width: "80%", height: 14 }} />
              <span className="hm-skel" style={{ width: "40%", height: 12 }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
