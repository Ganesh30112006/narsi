import { useId } from 'react';
import { Search, X } from 'lucide-react';
import fieldStyles from './Field.module.css';
import styles from './Misc.module.css';

interface SearchInputProps {
  value: string;
  onChange(value: string): void;
  label: string;
  placeholder?: string;
  className?: string;
}

export function SearchInput({ value, onChange, label, placeholder, className }: SearchInputProps) {
  const id = useId();
  return (
    <div className={[styles.search, className].filter(Boolean).join(' ')} role="search">
      <label htmlFor={id} className="visually-hidden">
        {label}
      </label>
      <Search size={16} className={fieldStyles.leadingIcon} aria-hidden />
      <input
        id={id}
        type="search"
        className={[fieldStyles.control, fieldStyles.withLeadingIcon, styles.searchInput].join(' ')}
        value={value}
        placeholder={placeholder ?? label}
        onChange={(event) => onChange(event.target.value)}
        autoComplete="off"
        spellCheck={false}
      />
      {value && (
        <button type="button" className={styles.searchClear} onClick={() => onChange('')} aria-label="Clear search">
          <X size={14} aria-hidden />
        </button>
      )}
    </div>
  );
}
