import { useCallback, useId, useRef, useState, type ReactNode } from 'react';

const DEFAULT_ACCEPT = 'image/*,.pdf';

export interface FileDropZoneProps {
  accept?: string;
  multiple?: boolean;
  disabled?: boolean;
  maxBytes?: number;
  maxBytesLabel?: string;
  onFilesSelected: (files: File[]) => void;
  /** Called when user picks/drops files that fail accept or size checks */
  onValidationError?: (message: string) => void;
  children: ReactNode;
  className?: string;
  activeClassName?: string;
  idleClassName?: string;
  inputId?: string;
  describedBy?: string;
}

function parseAcceptList(accept: string): { mimePrefixes: string[]; extensions: Set<string> } {
  const mimePrefixes: string[] = [];
  const extensions = new Set<string>();
  for (const part of accept.split(',').map((s) => s.trim()).filter(Boolean)) {
    if (part.startsWith('.')) {
      extensions.add(part.toLowerCase());
    } else if (part.endsWith('/*')) {
      mimePrefixes.push(part.toLowerCase());
    } else if (part.includes('/')) {
      mimePrefixes.push(part.toLowerCase());
    }
  }
  return { mimePrefixes, extensions };
}

function fileMatchesAccept(file: File, accept: string): boolean {
  const { mimePrefixes, extensions } = parseAcceptList(accept);
  if (mimePrefixes.length === 0 && extensions.size === 0) return true;
  const name = file.name.toLowerCase();
  const dot = name.lastIndexOf('.');
  const ext = dot >= 0 ? name.slice(dot) : '';
  if (extensions.size > 0 && ext && extensions.has(ext)) return true;
  const type = (file.type || '').toLowerCase();
  if (!type) return extensions.size > 0 && ext !== '' && extensions.has(ext);
  for (const p of mimePrefixes) {
    if (p.endsWith('/*')) {
      const base = p.slice(0, -2);
      if (type.startsWith(`${base}/`)) return true;
    } else if (type === p) {
      return true;
    }
  }
  return false;
}

export default function FileDropZone({
  accept = DEFAULT_ACCEPT,
  multiple = true,
  disabled = false,
  maxBytes,
  maxBytesLabel,
  onFilesSelected,
  onValidationError,
  children,
  className = '',
  activeClassName = 'border-blue-500 bg-blue-500/10',
  idleClassName = 'border-gray-700 hover:border-gray-600 hover:bg-gray-800/50',
  inputId: inputIdProp,
  describedBy,
}: FileDropZoneProps) {
  const reactId = useId();
  const inputId = inputIdProp ?? `file-drop-${reactId}`;
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const validateAndEmit = useCallback(
    (list: File[]) => {
      const valid: File[] = [];
      for (const file of list) {
        if (!fileMatchesAccept(file, accept)) {
          onValidationError?.(
            `"${file.name}" is not an allowed type. Use: ${accept.replace(/,/g, ', ')}`
          );
          continue;
        }
        if (maxBytes != null && file.size > maxBytes) {
          onValidationError?.(
            `"${file.name}" exceeds ${maxBytesLabel ?? formatBytes(maxBytes)}`
          );
          continue;
        }
        valid.push(file);
      }
      if (valid.length > 0) onFilesSelected(valid);
    },
    [accept, maxBytes, maxBytesLabel, onFilesSelected, onValidationError]
  );

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (disabled) return;
    validateAndEmit(Array.from(e.dataTransfer.files ?? []));
  };

  const onChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    validateAndEmit(Array.from(e.target.files ?? []));
    e.target.value = '';
  };

  const borderState = dragOver ? activeClassName : idleClassName;

  return (
    <div className={className}>
      <label
        htmlFor={inputId}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className={`flex flex-col items-center justify-center py-8 px-4 border-2 border-dashed rounded-xl bg-gray-800/30 transition-colors cursor-pointer focus-within:ring-2 focus-within:ring-blue-500/40 ${
          disabled ? 'opacity-50 cursor-not-allowed pointer-events-none' : ''
        } ${borderState}`}
      >
        <input
          ref={inputRef}
          id={inputId}
          type="file"
          multiple={multiple}
          accept={accept}
          disabled={disabled}
          onChange={onChange}
          className="sr-only"
          aria-describedby={describedBy}
        />
        {children}
      </label>
    </div>
  );
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(0)} MB`;
}
