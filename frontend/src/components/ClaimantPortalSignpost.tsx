import { Link } from 'react-router-dom';

export default function ClaimantPortalSignpost() {
  return (
    <div
      className="rounded-xl border border-emerald-500/20 bg-emerald-500/10 px-4 py-3 text-sm text-gray-300"
      role="note"
    >
      <span className="text-gray-400">Using a claim access token? </span>
      <Link
        to="/portal/login"
        className="font-medium text-emerald-400 hover:text-emerald-300 underline-offset-2 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50 rounded-sm"
      >
        Sign in to the Claimant Portal
      </Link>
    </div>
  );
}
