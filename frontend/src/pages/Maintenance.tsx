export default function Maintenance() {
  return (
    <div className="center-page">
      <div className="card">
        <h1>Down for maintenance</h1>
        <p>LedgerLab is down for scheduled maintenance. Please try again later.</p>
        <button type="button" className="btn-secondary" onClick={() => window.location.assign("/login")}>
          Try again
        </button>
      </div>
    </div>
  );
}
