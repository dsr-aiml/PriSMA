"use client";
import { useParams } from "next/navigation";
import Workspace from "@/components/workspace";

export default function AssessmentPage(){const params=useParams<{id:string}>();return <Workspace key={params.id} assessmentId={params.id}/>;}
