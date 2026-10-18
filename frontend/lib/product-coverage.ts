const labels: Record<string,string> = {
  inspected:"Inspected",publicly_documented:"Documented",referenced:"Referenced",declared:"In code",
  partial:"Partial",requires_login:"Requires login",requires_subscription:"Requires subscription",collection_failed:"Collection failed",
};
export function inspectionLabel(status:string){return labels[status]??"Unknown";}
export function barrierLabel(reason:string){return ({unsupported_browser:"Unsupported browser",access_challenge:"Access challenge",access_denied:"Access denied",authentication_required:"Requires login",subscription_required:"Requires subscription",error_page:"Error page",navigation_failed:"Navigation failed",navigation_timeout:"Navigation timeout"} as Record<string,string>)[reason]??reason.replaceAll("_"," ");}
export function workflowLabel(status:string,execution:string){
  if(status==="publicly_documented")return "Documented; execution untested";
  if(status==="inspected")return execution==="not_submitted"?"Form inspected; submission untested":"Disclosure inspected";
  return inspectionLabel(status);
}
