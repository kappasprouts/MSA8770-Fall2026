export interface ItExceptionCandidate {source: string; status: string; findings?: string[];}
export function isItActionable(record: ItExceptionCandidate): boolean;
