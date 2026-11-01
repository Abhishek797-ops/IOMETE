import coreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

/*
 * Flat config, using eslint-config-next's native flat exports.
 *
 * Not FlatCompat: eslint-config-next 16 ships flat config arrays directly, and running
 * them back through the eslintrc shim throws on its own plugin graph.
 */
const config = [
  ...coreWebVitals,
  ...nextTypescript,
  {
    ignores: [
      ".next/**",
      "node_modules/**",
      "playwright-report/**",
      "test-results/**",
      "next-env.d.ts",
    ],
  },
  {
    rules: {
      // `any` defeats the point of having types. Where it is genuinely unavoidable, a
      // comment has to say why.
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
];

export default config;
