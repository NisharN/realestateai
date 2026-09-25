import { redirect } from "next/navigation";

export default function IngestionRedirect() {
  redirect("/cowork?tab=data");
}
