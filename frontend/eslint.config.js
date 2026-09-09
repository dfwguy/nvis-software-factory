/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */
// eslint.config.js — lint gate for the SPA.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
import js from "@eslint/js";
import { defineConfig, globalIgnores } from "eslint/config";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig([
  globalIgnores(["dist", "../static/spa"]),
  {
    files: ["**/*.{ts,tsx}"],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
    rules: {
      // Mirrors the whitespace and comment hygiene ruff enforces on backend/, so both halves of
      // the product are checked to the same standard rather than one of them being on trust.
      "no-trailing-spaces": "error",
      "eol-last": ["error", "always"],
      "no-multiple-empty-lines": ["error", { max: 2, maxEOF: 0, maxBOF: 0 }],
      "spaced-comment": ["error", "always", { markers: ["/", "!"], block: { balanced: true } }],
      "no-multi-spaces": ["error", { ignoreEOLComments: true }],

      // A leading underscore is the declared way to say "this parameter exists to satisfy a
      // signature". Test doubles for `fetch` need both arguments typed even when only one is
      // read, and renaming a parameter is not worth suppressing the rule for.
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrors: "all", caughtErrorsIgnorePattern: "^_" },
      ],

      // A marker documents work nobody scheduled, and it rots. Track it in GitLab and link the
      // issue. Warning rather than error so an in-progress branch still builds.
      "no-warning-comments": [
        "warn",
        { terms: ["todo", "fixme", "xxx", "hack"], location: "anywhere" },
      ],

      // Unlike the reference app, this rule is an ERROR here and the code is written to satisfy
      // it: every loader in src/hooks awaits before it touches state, and the effects that call
      // them are abort-guarded. Doing it this way from the first commit is cheap; retrofitting it
      // across thirty views is not, which is exactly the lesson this application exists to teach.
      "react-hooks/set-state-in-effect": "error",
    },
  },
]);
