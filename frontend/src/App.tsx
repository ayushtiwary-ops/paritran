/**
 * Route table (react-router v7 data router).
 *
 * Screens per SPEC 10.3. Security Posture lands in Milestone 7; until
 * then its route renders the honest ComingNext placeholder so no
 * navigation dead-ends.
 */

import { createBrowserRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { Layout } from "./app/Layout";
import { RequireAuth } from "./app/RequireAuth";
import { CaseFile } from "./screens/CaseFile";
import { ComingNext } from "./screens/ComingNext";
import { Custody } from "./screens/Custody";
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
      { path: "casefile", element: <CaseFile /> },
      { path: "custody", element: <Custody /> },
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
