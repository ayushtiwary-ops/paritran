/**
 * Route table (react-router v7 data router).
 *
 * Screens per SPEC 10.3, all six live. The catch-all keeps the honest
 * ComingNext treatment so no navigation dead-ends.
 */

import { createBrowserRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { Layout } from "./app/Layout";
import { RequireAuth } from "./app/RequireAuth";
import { RouteError } from "./app/RouteError";
import { CaseFile } from "./screens/CaseFile";
import { ComingNext } from "./screens/ComingNext";
import { Custody } from "./screens/Custody";
import { Demo } from "./screens/Demo";
import { Discovery } from "./screens/Discovery";
import { Evaluation } from "./screens/Evaluation";
import { Login } from "./screens/Login";
import { Security } from "./screens/Security";

const router = createBrowserRouter([
  { path: "/login", element: <Login />, errorElement: <RouteError /> },
  {
    path: "/",
    element: (
      <RequireAuth>
        <Layout />
      </RequireAuth>
    ),
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Discovery /> },
      { path: "demo", element: <Demo /> },
      { path: "casefile", element: <CaseFile /> },
      { path: "custody", element: <Custody /> },
      { path: "evaluation", element: <Evaluation /> },
      { path: "security", element: <Security /> },
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
