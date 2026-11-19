import { useEffect, useState } from "react";
import { Card, Table, Button, Modal, Form, Input, Select, message, Tag } from "antd";
import { api } from "../api";

export default function Projects() {
  const [projects, setProjects] = useState<any[]>([]);
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();

  const load = () => api("/api/v1/projects").then(setProjects).catch(() => {});

  useEffect(() => {
    load();
  }, []);

  const onCreate = async (values: any) => {
    try {
      await api("/api/v1/projects", { method: "POST", body: JSON.stringify(values) });
      message.success("项目已创建");
      setOpen(false);
      form.resetFields();
      load();
    } catch (e: any) {
      message.error(e.message);
    }
  };

  return (
    <Card
      title="项目（自动化工程）"
      extra={<Button type="primary" onClick={() => setOpen(true)}>注册项目</Button>}
    >
      <Table
        rowKey="id"
        size="middle"
        dataSource={projects}
        pagination={false}
        columns={[
          { title: "ID", dataIndex: "id", width: 60 },
          { title: "名称", dataIndex: "name" },
          {
            title: "源码类型", dataIndex: "source_type", width: 100,
            render: (t) => <Tag>{t}</Tag>,
          },
          { title: "仓库", dataIndex: "repository_ref" },
          { title: "负责人", dataIndex: "owner", width: 110 },
          { title: "状态", dataIndex: "status", width: 90 },
        ]}
      />
      <Modal
        title="注册自动化工程"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
      >
        <Form form={form} layout="vertical" onFinish={onCreate}>
          <Form.Item name="name" label="项目名（小写字母/数字/中划线）" rules={[{ required: true }]}>
            <Input placeholder="robot-web-smoke" />
          </Form.Item>
          <Form.Item name="source_type" label="源码类型" rules={[{ required: true }]} initialValue="git">
            <Select options={[{ value: "git" }, { value: "svn" }]} />
          </Form.Item>
          <Form.Item name="repository_ref" label="仓库地址/引用" rules={[{ required: true }]}>
            <Input placeholder="https://git.example.com/team/web-tests" />
          </Form.Item>
          <Form.Item name="owner" label="负责人">
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
