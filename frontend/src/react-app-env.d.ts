/// <reference types="react-scripts" />
/// <reference types="react" />
/// <reference types="react-dom" />

declare namespace JSX {
  interface IntrinsicElements {
    [elemName: string]: any;
  }
  
  interface Element extends React.ReactElement<any, any> { }
}

// Ensure React types are available globally
declare global {
  namespace React {
    interface FormEvent<T = Element> extends SyntheticEvent<T> {
      target: EventTarget & T;
    }
    
    interface ChangeEvent<T = Element> extends SyntheticEvent<T> {
      target: EventTarget & T;
    }
  }
}
