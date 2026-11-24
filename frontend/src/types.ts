export type Artifact={id:string;user_id:string;session:string|null;layer:number;kind:string;title:string;content:string;created_at:string;active:boolean;payload:Record<string,any>};
export type Run={id:string;action:string;status:string;session:string;created_at:string;finished_at:string|null;input:Record<string,any>;result:Record<string,any>;error:string|null};
export type Trace={seq:number;run_id:string;type:string;data:Record<string,any>;created_at:string};
export type State={objects:Artifact[];runs:Run[];sessions:string[];edges:{source:string;target:string;relation:string}[]};
