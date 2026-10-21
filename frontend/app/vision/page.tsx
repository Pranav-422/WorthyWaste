import type { Metadata } from "next";
import { VisionApp } from "./VisionApp";

export const metadata: Metadata = {
  title: "WorthyWaste · Segregation check",
  description: "Upload a photo of household waste: OpenCV on AWS says separated or mixed, and the agent decides what happens next.",
};

// Public on purpose: this is the live endpoint anyone can try. Runs are stored face-blurred for 30 days
// (or until "Delete my data"), see vision/lambda_function.py.
export default function Page() {
  return <VisionApp />;
}
