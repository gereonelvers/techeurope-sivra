import { redirect } from "next/navigation";

// Root: redirect to the default skin.
export default function Home() {
  redirect("/site-a");
}
