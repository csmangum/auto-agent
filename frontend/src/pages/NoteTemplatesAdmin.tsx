import { useState } from 'react';
import PageHeader from '../components/PageHeader';
import {
  useNoteTemplates,
  useCreateNoteTemplate,
  useUpdateNoteTemplate,
  useDeleteNoteTemplate,
} from '../api/queries';
import type { NoteTemplate } from '../api/types';

function TemplateRow({
  template,
  onSave,
  onDelete,
  saving,
}: {
  template: NoteTemplate;
  onSave: (id: number, patch: Record<string, unknown>) => void;
  onDelete: (id: number) => void;
  saving: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [label, setLabel] = useState(template.label);
  const [body, setBody] = useState(template.body);
  const [category, setCategory] = useState(template.category ?? '');
  const [sortOrder, setSortOrder] = useState(template.sort_order);

  const reset = () => {
    setLabel(template.label);
    setBody(template.body);
    setCategory(template.category ?? '');
    setSortOrder(template.sort_order);
    setEditing(false);
  };

  const handleSave = () => {
    const patch: Record<string, unknown> = {};
    if (label !== template.label) patch.label = label;
    if (body !== template.body) patch.body = body;
    const newCat = category.trim() || null;
    if (newCat !== (template.category ?? null)) patch.category = newCat;
    if (sortOrder !== template.sort_order) patch.sort_order = sortOrder;
    if (Object.keys(patch).length > 0) onSave(template.id, patch);
    setEditing(false);
  };

  const active = template.is_active === 1 || template.is_active === true;

  return (
    <tr className={`hover:bg-gray-800/80 transition-colors ${!active ? 'opacity-50' : ''}`}>
      <td className="px-4 py-2.5 text-xs">
        {editing ? (
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            className="w-full bg-gray-800 border border-gray-600 rounded px-2 py-1 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        ) : (
          <span className="font-medium text-gray-200">{template.label}</span>
        )}
      </td>
      <td className="px-4 py-2.5 text-xs max-w-xs">
        {editing ? (
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={2}
            className="w-full bg-gray-800 border border-gray-600 rounded px-2 py-1 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500 resize-none"
          />
        ) : (
          <span className="text-gray-400 line-clamp-2">{template.body}</span>
        )}
      </td>
      <td className="px-4 py-2.5 text-xs">
        {editing ? (
          <input
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            placeholder="(none)"
            className="w-24 bg-gray-800 border border-gray-600 rounded px-2 py-1 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        ) : (
          <span className="text-gray-500">{template.category ?? '—'}</span>
        )}
      </td>
      <td className="px-4 py-2.5 text-xs text-center">
        {editing ? (
          <input
            type="number"
            min={0}
            value={sortOrder}
            onChange={(e) => setSortOrder(Number(e.target.value))}
            className="w-16 bg-gray-800 border border-gray-600 rounded px-2 py-1 text-sm text-gray-200 text-center focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        ) : (
          <span className="font-mono text-gray-400">{template.sort_order}</span>
        )}
      </td>
      <td className="px-4 py-2.5 text-xs text-center">
        <button
          onClick={() => onSave(template.id, { is_active: !active })}
          disabled={saving}
          className={`px-2 py-0.5 rounded text-xs font-medium transition-colors ${
            active
              ? 'bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30'
              : 'bg-gray-700/50 text-gray-500 hover:bg-gray-700'
          }`}
        >
          {active ? 'Active' : 'Inactive'}
        </button>
      </td>
      <td className="px-4 py-2.5 text-xs">
        <div className="flex items-center gap-1.5">
          {editing ? (
            <>
              <button
                onClick={handleSave}
                disabled={saving || !label.trim() || !body.trim()}
                className="px-2 py-1 text-xs bg-blue-600/20 text-blue-400 rounded hover:bg-blue-600/30 disabled:opacity-40 transition-colors"
              >
                Save
              </button>
              <button
                onClick={reset}
                className="px-2 py-1 text-xs bg-gray-700/50 text-gray-400 rounded hover:bg-gray-700 transition-colors"
              >
                Cancel
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => setEditing(true)}
                className="px-2 py-1 text-xs bg-gray-700/50 text-gray-400 rounded hover:bg-gray-700 hover:text-gray-200 transition-colors"
              >
                Edit
              </button>
              <button
                onClick={() => onDelete(template.id)}
                disabled={saving}
                className="px-2 py-1 text-xs bg-red-600/10 text-red-400/70 rounded hover:bg-red-600/20 hover:text-red-400 disabled:opacity-40 transition-colors"
              >
                Delete
              </button>
            </>
          )}
        </div>
      </td>
    </tr>
  );
}

export default function NoteTemplatesAdmin() {
  const { data: templates, isLoading, error } = useNoteTemplates();
  const createMutation = useCreateNoteTemplate();
  const updateMutation = useUpdateNoteTemplate();
  const deleteMutation = useDeleteNoteTemplate();

  const [newLabel, setNewLabel] = useState('');
  const [newBody, setNewBody] = useState('');
  const [newCategory, setNewCategory] = useState('');
  const [newSortOrder, setNewSortOrder] = useState(0);

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newLabel.trim() || !newBody.trim()) return;
    createMutation.mutate(
      {
        label: newLabel.trim(),
        body: newBody.trim(),
        category: newCategory.trim() || undefined,
        sort_order: newSortOrder,
      },
      {
        onSuccess: () => {
          setNewLabel('');
          setNewBody('');
          setNewCategory('');
          setNewSortOrder(0);
        },
      },
    );
  };

  const handleSave = (id: number, patch: Record<string, unknown>) => {
    updateMutation.mutate({ id, ...patch });
  };

  const handleDelete = (id: number) => {
    if (!window.confirm('Permanently delete this template? Consider deactivating instead.')) {
      return;
    }
    deleteMutation.mutate(id);
  };

  const saving = createMutation.isPending || updateMutation.isPending || deleteMutation.isPending;

  const mutationError =
    createMutation.error ?? updateMutation.error ?? deleteMutation.error;

  if (isLoading) {
    return (
      <div className="space-y-8 animate-fade-in">
        <PageHeader title="Note Templates" subtitle="Manage adjuster quick-insert templates" />
        <div className="h-48 rounded-xl border border-gray-700/50 bg-gray-800/50 skeleton-shimmer" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6 animate-fade-in">
        <PageHeader title="Note Templates" />
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4">
          <p className="text-sm text-red-400">
            {error instanceof Error ? error.message : 'Failed to load templates'}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-fade-in">
      <PageHeader
        title="Note Templates"
        subtitle="Manage adjuster quick-insert templates for claim notes"
      />

      {mutationError && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4">
          <p className="text-sm text-red-400">
            {mutationError instanceof Error ? mutationError.message : 'Operation failed'}
          </p>
        </div>
      )}

      {/* Create form */}
      <section className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-4">Add Template</h3>
        <form onSubmit={handleCreate} className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="tpl-label" className="block text-xs text-gray-500 mb-1">
                Label *
              </label>
              <input
                id="tpl-label"
                value={newLabel}
                onChange={(e) => setNewLabel(e.target.value)}
                maxLength={120}
                required
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
                placeholder="e.g. Initial Contact"
              />
            </div>
            <div className="flex gap-3">
              <div className="flex-1">
                <label htmlFor="tpl-category" className="block text-xs text-gray-500 mb-1">
                  Category
                </label>
                <input
                  id="tpl-category"
                  value={newCategory}
                  onChange={(e) => setNewCategory(e.target.value)}
                  maxLength={80}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  placeholder="(optional)"
                />
              </div>
              <div className="w-24">
                <label htmlFor="tpl-sort" className="block text-xs text-gray-500 mb-1">
                  Order
                </label>
                <input
                  id="tpl-sort"
                  type="number"
                  min={0}
                  value={newSortOrder}
                  onChange={(e) => setNewSortOrder(Number(e.target.value))}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 text-center focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
            </div>
          </div>
          <div>
            <label htmlFor="tpl-body" className="block text-xs text-gray-500 mb-1">
              Body *
            </label>
            <textarea
              id="tpl-body"
              value={newBody}
              onChange={(e) => setNewBody(e.target.value)}
              rows={3}
              maxLength={5000}
              required
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500 resize-none"
              placeholder="Template text with optional [PLACEHOLDERS]"
            />
          </div>
          <div className="flex justify-end">
            <button
              type="submit"
              disabled={saving || !newLabel.trim() || !newBody.trim()}
              className="px-4 py-2 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-500 disabled:opacity-40 transition-colors"
            >
              {createMutation.isPending ? 'Creating...' : 'Add Template'}
            </button>
          </div>
        </form>
      </section>

      {/* Templates table */}
      <section className="bg-gray-800/50 rounded-xl border border-gray-700/50 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b border-gray-700/50 text-left text-xs uppercase tracking-wider text-gray-500">
                <th className="px-4 py-3 font-medium">Label</th>
                <th className="px-4 py-3 font-medium">Body</th>
                <th className="px-4 py-3 font-medium">Category</th>
                <th className="px-4 py-3 font-medium text-center">Order</th>
                <th className="px-4 py-3 font-medium text-center">Status</th>
                <th className="px-4 py-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-700/30">
              {templates && templates.length > 0 ? (
                templates.map((t) => (
                  <TemplateRow
                    key={t.id}
                    template={t}
                    onSave={handleSave}
                    onDelete={handleDelete}
                    saving={saving}
                  />
                ))
              ) : (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center text-sm text-gray-500">
                    No templates configured yet. Add one above.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
