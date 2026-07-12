/**
 * Route table (react-router v7 data router).
 *
 * Screens per SPEC 10.3. Case File and Custody land next (Milestone 6)
 * and Security Posture in Milestone 7; until then their routes render
 * the honest ComingNext placeholder so no navigation dead-ends.
 */

import { createBrowserRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { Layout } from "./app/Layout";
import { RequireAuth } from "./app/RequireAuth";
import { ComingNext } from "./screens/ComingNext";
import { Discovery } from "./screens/Discovery";
import { Evaluation } from "./screens/Evaluation";
import { Login } from "./screens/Login";

const router = createBrowserRouter([
  { path: "/login", element: <Login /> },
  {
    path: "/",
    element: (
      <RequireAuth>
        <Layout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Discovery /> },
      {
        path: "casefile",
        element: (
          <ComingNext
            title="Case File"
            milestone="Milestone 6"
            summary={
              "Money trail animation, verbatim v2 section quotes, the" +
              " Section 63 certificate, and the F9 claim panel."
            }
          />
        ),
      },
      {
        path: "custody",
        element: (
          <ComingNext
            title="Custody Ledger"
            milestone="Milestone 6"
            summary={
              "The hash-chained evidence ledger with prev-hash linkage" +
              " drawn, and the auditor's live tamper test."
            }
          />
        ),
      },
      { path: "evaluation", element: <Evaluation /> },
      {
        path: "security",
        element: (
          <ComingNext
            title="Security Posture"
            milestone="Milestone 7"
            summary={
              "OWASP coverage checklist, scanner artifact summaries, and" +
              " the egress self-test panel from /api/security/posture."
            }
          />
        ),
      },
      {
        path: "*",
        element: (
          <ComingNext
            title="Not found"
            milestone="no milestone"
            summary="This route does not exist. Use the navigation on the left."
          />
        ),
      },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
