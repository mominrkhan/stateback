import type { Preview } from "@storybook/react-vite";
import "../src/design/global.css";

const preview: Preview = {
  parameters: {
    layout: "centered",
    backgrounds: { default: "stateback", values: [{ name: "stateback", value: "#0b0e12" }] },
    a11y: { test: "error" },
  },
};
export default preview;
