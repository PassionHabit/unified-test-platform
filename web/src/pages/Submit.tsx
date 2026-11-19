import { useEffect, useState } from "react";
import { Card, Form, Select, Input, Button, message, Space, Typography } from "antd";
import { api } from "../api";

export default function Submit() {
  const [projects, setProjects] = useState<any[]>([]);
  const [profiles, setProfiles] = useState<any[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm();

  useEffect(() => {
    api("/api/v1/projects").then(setProjects).catch(() => {});
  }, []);

  const loadProfiles = (project: string) => {
    api(`/api/v1/projects/${project}/profiles`).then(setProfiles).catch(() => setProfiles([]));
  };

  const onFinish = async (values: any) => {
    setSubmitting(true);
    try {
      let parameters: any = {};
      if (values.parameters?.trim()) {
        parameters = JSON.parse(values.parameters);
      }
      const body: any = {
        project_id: values.project,
        profile: values.profile || "default",
        source_revision: values.source_revision || "main",
        parameters,
        caller: { type: "human" },
      };
      const exec = await api("/api/v1/executions", {
        method: "POST",
        body: JSON.stringify(body),
      });
      message.success(`已提交：执行 #${exec.id}（${exec.status}）`);
    } catch (e: any) {
      message.error(`提交失败：${e.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card title="提交执行" style={{ maxWidth: 720 }}>
      <Form form={form} layout="vertical" onFinish={onFinish}>
        <Form.Item name="project" label="项目" rules={[{ required: true }]}>
          <Select
            placeholder="选择自动化工程"
            onChange={loadProfiles}
            options={projects.map((p) => ({ value: p.name, label: `${p.name}（${p.source_type}）` }))}
          />
        </Form.Item>
        <Form.Item name="profile" label="执行配置（Profile）">
          <Select
            placeholder="default"
            allowClear
            options={profiles.map((p) => ({ value: p.name, label: `${p.name} · ${p.runtime_image_ref}` }))}
          />
        </Form.Item>
        <Form.Item name="source_revision" label="源码版本">
          <Input placeholder="main（提交时解析并固化为精确版本）" />
        </Form.Item>
        <Form.Item
          name="parameters"
          label="执行参数（JSON）"
          extra='例如 {"environment": {"base_url": "https://test.example"}}'
        >
          <Input.TextArea rows={4} placeholder="{}" />
        </Form.Item>
        <Space>
          <Button type="primary" htmlType="submit" loading={submitting}>
            提交
          </Button>
          <Typography.Text type="secondary">提交后异步执行，可在「执行列表」跟踪</Typography.Text>
        </Space>
      </Form>
    </Card>
  );
}
